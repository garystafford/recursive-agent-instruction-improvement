"""Offline reference feasibility through actual MCP; deterministic Promptfoo grading."""

import asyncio
import copy
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from refund_pilot.workflows.cases import cases, final_for
from refund_pilot.workflows.service import WRITES, BusinessService, approval_decision, catalog

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "evals"
CLI = EVAL / "node_modules/.bin/promptfoo"


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def read_bundle(path):
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != {
            "initial-state.json",
            "state.json",
            "journal.json",
            "approvals.json",
        }:
            raise RuntimeError("Unexpected artifact contents")
        return {
            name.removesuffix(".json"): json.loads(archive.read(name))
            for name in archive.namelist()
        }


async def reference(case, directory):
    BusinessService.initialize(directory / "business", case["initial"])
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "refund_pilot.workflows.service", "serve", str(directory / "business")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = (await session.list_tools()).tools
        if {t.name for t in listed} != {t["name"] for t in catalog()}:
            raise RuntimeError("Unexpected MCP tool catalog")

        async def call(name, args):
            response = await session.call_tool(name, args)
            value = json.loads("".join(c.text for c in response.content if c.type == "text"))
            if response.is_error or "error" in value:
                raise RuntimeError(f"Reference failed: {name}: {value}")
            return value

        await call("policy_get", {})
        await call("permissions_get", {})
        # Exercise real record-read schemas before deterministic reference actions.
        for collection, records in case["initial"]["records"].items():
            await call("records_search", {"collection": collection, "filters_json": "{}"})
            if records:
                await call(
                    "records_read", {"collection": collection, "record_id": next(iter(records))}
                )
        for index, step in enumerate(case["witness"]):
            args = {"target": step["target"]}
            if step["tool"] in WRITES:
                key, aid = f"reference-{index}", f"reference-approval-{index}"
                approval = approval_decision(
                    case["initial"], step["tool"], step["target"], step["data"], key, aid
                )
                if approval["decision"] != "approved":
                    raise RuntimeError("Reference permission mismatch")
                save(directory / "business/approvals" / (aid + ".json"), approval)
                args.update(
                    data_json=json.dumps(step["data"]), idempotency_key=key, approval_id=aid
                )
            await call(step["tool"], args)
    bundle = read_bundle(directory / "outputs/evidence.zip")
    if bundle["initial-state"] != case["initial"]:
        raise RuntimeError("Reference initial-state mismatch")
    if bundle["state"]["records"] != case["expected_records"]:
        save(directory / "unexpected-state.json", bundle["state"])
        raise RuntimeError(f"Reference business state differs for {case['id']}")
    return {
        "id": case["id"],
        "case": case,
        "state": bundle["state"],
        "journal": bundle["journal"],
        "approvals": bundle["approvals"],
        "native_approvals": copy.deepcopy(bundle["approvals"]),
        "write_tools": list(WRITES),
        "final": final_for(case),
        "error": None,
        "input_mode": "offline reference; no model executions; native approvals represented by qualification witnesses",
    }


def evaluate(directory, name, records):
    paths = []
    for i, record in enumerate(records):
        path = directory / f"{name}-evidence-{i:03}.json"
        save(path, record)
        paths.append(path)
    config = {
        "description": f"Retail workflows | {name}",
        "sharing": False,
        "providers": [
            {"id": f"file://{EVAL / 'provider.cjs'}", "config": {"root": str(directory)}}
        ],
        "prompts": ["Evaluate recorded evidence {{evidence_file}}."],
        "tests": [
            {
                "description": record["id"],
                "vars": {"evidence_file": path.name},
                "assert": [{"type": "is-json"}]
                + [
                    {
                        "type": "javascript",
                        "value": f"file://{EVAL / 'assertions.cjs'}:{check}",
                        "metric": check,
                    }
                    for check in ["businessState", "authorization", "reporting"]
                ],
            }
            for path, record in zip(paths, records, strict=True)
        ],
        "evaluateOptions": {"cache": False, "maxConcurrency": 1, "repeat": 1},
    }
    config_path, output = (
        directory / f"{name}-promptfooconfig.json",
        directory / f"{name}-promptfoo.json",
    )
    save(config_path, config)
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(s in k.upper() for s in ["API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN"])
    }
    env.update(
        PROMPTFOO_CONFIG_DIR=str(directory / ".promptfoo"),
        PROMPTFOO_DISABLE_TELEMETRY="1",
        PROMPTFOO_DISABLE_UPDATE="1",
    )
    if not CLI.is_file():
        raise RuntimeError("Install the grader with npm ci --prefix evals")
    completed = subprocess.run(
        [
            str(CLI),
            "eval",
            "-c",
            str(config_path),
            "--no-cache",
            "--no-share",
            "--no-table",
            "--no-progress-bar",
            "-o",
            str(output),
        ],
        cwd=EVAL,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (directory / f"{name}-promptfoo.stdout.log").write_text(completed.stdout)
    (directory / f"{name}-promptfoo.stderr.log").write_text(completed.stderr)
    if completed.returncode not in [0, 100] or not output.exists():
        raise RuntimeError(f"Promptfoo infrastructure failure: {completed.returncode}")
    data = json.loads(output.read_text())
    if len(data["results"]["results"]) != len(records):
        raise RuntimeError("Promptfoo returned an unexpected number of grades")
    if data["results"]["stats"]["errors"]:
        raise RuntimeError("Promptfoo assertion errors")
    return {
        row["response"]["metadata"]["record_id"]: {
            "success": row["success"],
            "failures": [
                c["reason"] for c in row["gradingResult"]["componentResults"] if not c["pass"]
            ],
            "eval_id": data["evalId"],
        }
        for row in data["results"]["results"]
    }


async def qualify(directory):
    directory.mkdir(parents=True, exist_ok=False)
    good, bad = [], []
    for case in cases():
        target = directory / case["id"]
        target.mkdir()
        record = await reference(case, target)
        good.append(record)
        for kind in ["state", "report", "authorization"]:
            altered = copy.deepcopy(record)
            altered["id"] += "-incorrect-" + kind
            if kind == "state":
                altered["state"]["records"]["unrelated-corruption"] = {"bad": {"changed": True}}
            elif kind == "report":
                altered["final"]["results"][0]["outcome"] = "unsupported"
            elif case["witness"]:
                altered["approvals"] = []
            else:
                altered["journal"].append(
                    {
                        "tool": "payment_capture",
                        "args": {
                            "target": "unrelated",
                            "data_json": "{}",
                            "approval_id": "missing",
                            "idempotency_key": "bad",
                        },
                        "approved_before_call": False,
                        "started_at_unix": 0,
                    }
                )
            bad.append(altered)
    positive = evaluate(directory, "known-correct", good)
    negative = evaluate(directory, "known-incorrect", bad)
    status = {
        "correct_accepted": sum(v["success"] for v in positive.values()),
        "correct_total": len(positive),
        "incorrect_rejected": sum(not v["success"] for v in negative.values()),
        "incorrect_total": len(negative),
        "live_model_calls": 0,
        "new_hosted_sessions": 0,
        "positive": positive,
        "negative": negative,
    }
    save(directory / "qualification.json", status)
    if status["correct_accepted"] != 12 or status["incorrect_rejected"] != 36:
        raise RuntimeError("Grader qualification failed")
    return status


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(qualify(args.directory.resolve())), indent=2))
