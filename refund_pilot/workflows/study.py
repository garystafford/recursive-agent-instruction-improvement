"""Run an isolated instruction-improvement study on synthetic retail cases."""

import argparse
import asyncio
import csv
import fcntl
import json
import os
import random
import statistics
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from refund_pilot.workflows import hosted, revision
from refund_pilot.workflows.cases import cases, request_text
from refund_pilot.workflows.qualification import ROOT, evaluate, qualify, save
from refund_pilot.workflows.service import catalog

PROTOCOL = ROOT / "docs/cumulative-instruction-improvement-protocol.md"
BASELINE = ROOT / "prompts/workflow-baseline.txt"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Rates(Config):
    input: float = Field(gt=0)
    cache_read: float = Field(ge=0)
    cache_write: float = Field(ge=0)
    output: float = Field(gt=0)


class Study(Config):
    development_cases: list[str] = Field(min_length=1)
    evaluation_rounds: list[list[str]] = Field(min_length=1)
    repetitions: int = Field(ge=1)
    budget_usd: float = Field(gt=0)
    task_model_allowance_usd: float = Field(gt=0)
    hosting_allowance_usd_per_task: float = Field(ge=0)
    pricing_usd_per_million: Rates

    def validate_cases(self, available):
        groups = [self.development_cases, *self.evaluation_rounds]
        ids = [case_id for group in groups for case_id in group]
        if any(not group for group in groups) or len(ids) != len(set(ids)):
            raise ValueError(
                "Development and each evaluation round need distinct nonempty case sets"
            )
        if unknown := set(ids) - set(available):
            raise ValueError("Unknown case IDs: " + ", ".join(sorted(unknown)))


def read(path):
    return json.loads(path.read_text())


def source_hashes():
    paths = [
        PROTOCOL,
        BASELINE,
        ROOT / "requirements.lock.txt",
        ROOT / "requirements-hosted.lock.txt",
        ROOT / "evals/package-lock.json",
        *(ROOT / "refund_pilot").rglob("*.py"),
        *(ROOT / "evals").glob("*.cjs"),
    ]
    return {str(path.relative_to(ROOT)): revision.file_sha(path) for path in sorted(paths)}


def plan(directory, config, available):
    manifest = directory / "manifest.json"
    frozen = {
        "settings": config.model_dump(),
        "source": source_hashes(),
        "cases_sha256": revision.sha(available),
    }
    if manifest.exists():
        if read(manifest) != frozen:
            raise RuntimeError("Study settings or frozen inputs changed")
    else:
        save(manifest, frozen)
    return frozen


def evidence_for(attempt_id, version_id, record, verdict, target):
    traces = read(target / "official-traces.json")
    items = read(target / "server-items.json")
    operations = [
        json.loads(line) for line in (target / "operation-timing.jsonl").read_text().splitlines()
    ]
    index = {
        f"j{i}": {"type": "business_call", "tool": event["tool"]}
        for i, event in enumerate(record["journal"], 1)
    }
    index.update({"i:" + item["id"]: {"type": item["type"]} for item in items})
    for trace in traces:
        for resource in trace["otlp"].get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope["spans"]:
                    index["s:" + span["spanId"]] = {"type": "span", "name": span["name"]}
    return {
        "attempt_id": attempt_id,
        "scenario_id": record["case"]["id"],
        "instruction_version": version_id,
        "classification": "valid_measured_attempt",
        "request": request_text(record["case"]),
        "initial_state": record["case"]["initial"],
        "final_state": record["state"],
        "final_output": record["final"],
        "business_journal": record["journal"],
        "native_approvals": record["native_approvals"],
        "official_traces": traces,
        "completed_items": items,
        "controller_operations": operations,
        "trace_index": index,
        "correctness_results": verdict,
        "metrics": {
            key: record[key]
            for key in (
                "task_seconds",
                "setup_seconds",
                "full_run_seconds",
                "estimated_task_model_usd",
                "usage",
                "llm_calls",
                "tool_calls",
                "business_tool_calls",
                "approval_calls",
            )
        },
    }


def instructions_version(version_id, instructions, changes, conclusion):
    return {
        "version_id": version_id,
        "instructions": instructions,
        "sha256": revision.sha_text(instructions),
        "changes": changes,
        "conclusion": conclusion,
    }


def schedule(case_ids, versions, repetitions):
    for rep in range(repetitions):
        for i, case_id in enumerate(case_ids):
            offset = (i + rep) % len(versions)
            for version in versions[offset:] + versions[:offset]:
                yield case_id, version, rep + 1


def prepare_revision(target, prompt, package):
    target.mkdir(exist_ok=True)
    if (target / "state.json").exists():
        if read(target / "expanded-evidence.json") != package:
            raise RuntimeError("Frozen revision evidence changed")
        return
    coverage = revision.verify_history(package)
    args = revision.request_arguments(prompt, revision.pack_history(package))
    save(target / "expanded-evidence.json", package)
    save(target / "coverage.json", coverage)
    save(target / "request.json", args)
    save(target / "state.json", {"status": "prepared", "request_sha256": revision.sha(args)})


def summarize(attempts, revision_costs, hosting):
    grouped = {}
    for phase, attempt in attempts:
        key = (phase, attempt["instruction_version"])
        grouped.setdefault(key, []).append(attempt)
    summaries = []
    for (phase, version), group in grouped.items():
        metrics = [a["metrics"] for a in group]
        passes = sum(a["correctness_results"]["success"] for a in group)
        cost = sum(row["estimated_task_model_usd"] for row in metrics)
        summaries.append(
            {
                "phase": phase,
                "version": version,
                "attempts": len(group),
                "passed": passes,
                "median_task_seconds": statistics.median(row["task_seconds"] for row in metrics),
                "mean_task_model_usd": cost / len(group),
                "task_model_usd_per_success": cost / passes if passes else None,
            }
        )
    comparisons = []
    for (phase, version), candidate in grouped.items():
        if phase == "development" or version != "V" + phase.removeprefix("evaluation-"):
            continue
        for reference in dict.fromkeys(("V0", f"V{int(version[1:]) - 1}")):
            baseline = grouped[(phase, reference)]
            for case_id in sorted({a["scenario_id"] for a in candidate}):
                left = [a for a in baseline if a["scenario_id"] == case_id]
                right = [a for a in candidate if a["scenario_id"] == case_id]
                left.sort(key=lambda a: a["attempt_id"])
                right.sort(key=lambda a: a["attempt_id"])
                change = {
                    "phase": phase,
                    "case": case_id,
                    "candidate": version,
                    "reference": reference,
                    "pairs": len(left),
                }
                for field, reduce in [
                    ("task_seconds", statistics.median),
                    ("estimated_task_model_usd", statistics.mean),
                ]:
                    pairs = [
                        (a["metrics"][field], b["metrics"][field])
                        for a, b in zip(left, right, strict=True)
                    ]

                    def percent(sample, reduce=reduce):
                        before, after = zip(*sample)
                        original = reduce(before)
                        return 100 * (reduce(after) / original - 1) if original else None

                    point = percent(pairs)
                    interval = None
                    if len(pairs) >= 5 and point is not None:
                        rng = random.Random(0)
                        boot = [percent(rng.choices(pairs, k=len(pairs))) for _ in range(2000)]
                        if None not in boot:
                            cuts = statistics.quantiles(boot, n=40)
                            interval = [cuts[0], cuts[-1]]
                    change[field] = {
                        "change_percent": point,
                        "paired_95_percent_interval": interval,
                    }
                comparisons.append(change)
    equal_case_changes = []
    by_comparison = {(row["phase"], row["candidate"], row["reference"]) for row in comparisons}
    for phase, candidate, reference in sorted(by_comparison):
        rows = [
            row
            for row in comparisons
            if (row["phase"], row["candidate"], row["reference"]) == (phase, candidate, reference)
        ]
        result = {"phase": phase, "candidate": candidate, "reference": reference}
        for key in ("task_seconds", "estimated_task_model_usd"):
            values = [row[key]["change_percent"] for row in rows]
            result[key] = statistics.mean(values) if None not in values else None
        equal_case_changes.append(result)
    return {
        "summary": summaries,
        "per_case_comparisons": comparisons,
        "equal_case_weighted_change_percent": equal_case_changes,
        "revision_estimates_usd": revision_costs,
        "hosting_allowances_usd": hosting,
        "confidence_note": "Paired bootstrap intervals require at least five repetitions here. Small runs are feasibility checks. Review correctness and uncertainty against the protocol before selecting a version.",
    }


async def run(directory, config):
    available = {case["id"]: case for case in cases()}
    config.validate_cases(available)
    frozen = plan(directory, config, available)
    pricing = config.pricing_usd_per_million.model_dump()
    charge = config.task_model_allowance_usd + config.hosting_allowance_usd_per_task
    qualification_dir = directory / "qualification"
    if not (qualification_dir / "qualification.json").is_file():
        await qualify(qualification_dir)
    qualification = read(qualification_dir / "qualification.json")
    if qualification["correct_accepted"] != 12 or qualification["incorrect_rejected"] != 36:
        raise RuntimeError("Offline qualification failed")
    attempts, versions, revision_history, revision_costs = [], [], [], []
    accounted = 0.0
    versions.append(
        instructions_version("V0", BASELINE.read_text(), [], "Competent shared baseline")
    )

    def verify():
        if source_hashes() != frozen["source"]:
            raise RuntimeError("Frozen source changed during the study")

    async def measure(phase, case_ids, phase_versions):
        nonlocal accounted
        target = directory / phase
        target.mkdir(exist_ok=True)
        staged = []
        for case_id, version, repetition in schedule(case_ids, phase_versions, config.repetitions):
            case = available[case_id]
            version_id = version["version_id"]
            attempt_id = f"{phase}-{case_id}-r{repetition:03}-{version_id}"
            path = target / attempt_id
            verify()
            if (path / "result.json").is_file():
                record = read(path / "result.json")
            elif path.exists():
                raise RuntimeError(f"Unresolved execution in {path}; inspect before resuming")
            else:
                if accounted + charge > config.budget_usd:
                    raise RuntimeError("Remaining budget does not cover another task reservation")
                record = await hosted.task(
                    path, case, version["instructions"], pricing, config.task_model_allowance_usd
                )
            if record["status"] != "completed":
                raise RuntimeError(
                    f"Incomplete execution in {path}; its reservation remains unresolved"
                )
            cost = record["estimated_task_model_usd"]
            accounted += cost + config.hosting_allowance_usd_per_task
            if cost > config.task_model_allowance_usd:
                raise RuntimeError(f"Observed cost exceeded the task allowance in {path}")
            staged.append((version_id, {**record, "id": attempt_id}, path))
        # Saved verdicts keep the next revision payload stable when a process resumes.
        grades_file = target / "grades.json"
        if not grades_file.is_file():
            verify()
            save(grades_file, evaluate(target, "grades", [record for _, record, _ in staged]))
        grades = read(grades_file)
        for version_id, record, path in staged:
            attempt = evidence_for(record["id"], version_id, record, grades[record["id"]], path)
            attempts.append((phase, attempt))
        save(
            directory / "summary.json",
            summarize(
                attempts, revision_costs, len(attempts) * config.hosting_allowance_usd_per_task
            ),
        )

    await measure("development", config.development_cases, versions)
    for number, evaluation_cases in enumerate(config.evaluation_rounds, 1):
        verify()
        history = [attempt for _, attempt in attempts]
        context = {
            "study": "Synthetic retail instruction improvement",
            "required_history_attempt_ids": [a["attempt_id"] for a in history],
            "task_agent": {"model": hosted.MODEL, "effort": "low", "runtime": "openai_hosted"},
            "tool_catalog": catalog(),
            "decision_rules": "Preserve correctness and authorization. Apply the protocol's 5% tolerances. Treat small samples as inconclusive.",
            "measurement": "Task time is submission through final response handling. Estimated task-model costs exclude hosting and revision. Tool counts here include MCP business and native approval calls. Hosted generation spans are a separate count.",
        }
        package = {
            "fixed_study_context": context,
            "instruction_history": {
                "original_version": "V0",
                "preceding_version": versions[-1]["version_id"],
                "versions": versions.copy(),
            },
            "execution_history": history,
            "prior_revision_attempts": revision_history.copy(),
            "conclusions_and_faults": {
                "conclusions": summarize(
                    attempts, revision_costs, len(attempts) * config.hosting_allowance_usd_per_task
                ),
                "infrastructure_diagnostics": "Only completed measurements are submitted. The runner stops on incomplete measurements and preserves them locally for classification.",
            },
        }
        target = directory / f"revision-{number}"
        prepare_revision(target, revision.protocol_prompt(PROTOCOL.read_text()), package)
        candidate = await revision.generate(target, verify, accounted, config.budget_usd, pricing)
        revision_state = read(target / "state.json")
        cost = revision_state["cost_usd"]
        revision_costs.append(cost)
        accounted += cost
        if candidate.status == "insufficient_evidence":
            raise RuntimeError(
                f"Revision reported insufficient evidence; see {target / 'candidate.json'}"
            )
        versions.append(
            instructions_version(
                f"V{number}",
                candidate.instructions,
                [change.model_dump() for change in candidate.changes],
                candidate.rationale,
            )
        )
        revision_history.append(
            {
                "version": f"V{number}",
                "request": {
                    key: value
                    for key, value in read(target / "request.json").items()
                    if key != "input"
                },
                "input": package,
                "response": read(target / "response.json"),
                "usage": revision_state["usage"],
                "estimated_model_usd": cost,
                "generation_seconds": revision_state["generation_seconds"],
            }
        )
        compare = [versions[0], *versions[-2:]] if number > 1 else versions.copy()
        await measure(f"evaluation-{number}", evaluation_cases, compare)
    with (directory / "comparison.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "phase",
                "attempt",
                "case",
                "version",
                "passed",
                "task_seconds",
                "estimated_task_model_usd",
            ]
        )
        for phase, attempt in attempts:
            writer.writerow(
                [
                    phase,
                    attempt["attempt_id"],
                    attempt["scenario_id"],
                    attempt["instruction_version"],
                    attempt["correctness_results"]["success"],
                    attempt["metrics"]["task_seconds"],
                    attempt["metrics"]["estimated_task_model_usd"],
                ]
            )
    return directory / "summary.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    check = sub.add_parser("check", help="Qualify the tool environment and grader offline")
    check.add_argument("--out", type=Path, required=True)
    start = sub.add_parser("run", help="Run or resume a paid study")
    start.add_argument("--config", type=Path, required=True)
    start.add_argument("--out", type=Path, required=True)
    start.add_argument("--allow-paid", action="store_true", required=True)
    args = parser.parse_args()
    directory = args.out.resolve()
    if args.mode == "check":
        result = asyncio.run(qualify(directory))
        print(
            f"{result['correct_accepted']} valid examples accepted; {result['incorrect_rejected']} invalid examples rejected"
        )
        return
    config = Study.model_validate_json(args.config.read_text())
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in your shell before starting a paid study")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "study.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(asyncio.run(run(directory, config)))


if __name__ == "__main__":
    main()
