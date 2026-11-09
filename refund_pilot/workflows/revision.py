"""Protocol-owned, cumulative instruction revision through one Responses request."""

import copy
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from refund_pilot.workflows.costs import estimate
from refund_pilot.workflows.qualification import save

MODEL = "gpt-6.1-sol"
CONTEXT_TOKENS = 1_050_000
MAX_OUTPUT_TOKENS = 128_000  # Native limit, not an instruction-length gate.


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceReference(ClosedModel):
    attempt_id: str = Field(
        description="An exact attempt_id from execution_history, such as baseline-T01."
    )
    trace_refs: list[str] = Field(
        description="One or more exact keys in that attempt's trace_index, such as j1 or s:<spanId>. Do not invent identifiers."
    )


class InstructionChange(ClosedModel):
    summary: str
    evidence_refs: list[EvidenceReference]
    expected_correctness_effect: str
    expected_cost_effect: str
    expected_time_effect: str
    regression_risks: list[str]


class InstructionRevision(ClosedModel):
    status: Literal["revised", "unchanged", "insufficient_evidence"]
    instructions: str | None
    rationale: str
    changes: list[InstructionChange]
    evidence_limitations: list[str]
    outside_instruction_scope: list[str]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protocol_prompt(protocol):
    section = protocol.split("## General instruction-revision prompt\n", 1)[1]
    return section.split("```text\n", 1)[1].split("\n```", 1)[0]


def pack_history(value):
    """Losslessly intern repeated large JSON subtrees inside the actual request."""
    counts = Counter()

    def count(node):
        encoded = canonical(node)
        if len(encoded) >= 256:
            counts[encoded] += 1
        if isinstance(node, dict):
            if "$history_ref" in node:
                raise ValueError("Reserved history-reference key in source evidence")
            for child in node.values():
                count(child)
        elif isinstance(node, list):
            for child in node:
                count(child)

    count(value)
    pool, names = {}, {}

    def encode(node):
        encoded = canonical(node)
        if len(encoded) >= 256 and counts[encoded] > 1:
            if encoded not in names:
                name = "h" + str(len(names) + 1)
                names[encoded] = name
                pool[name] = descend(node)
            return {"$history_ref": names[encoded]}
        return descend(node)

    def descend(node):
        if isinstance(node, dict):
            return {k: encode(v) for k, v in node.items()}
        if isinstance(node, list):
            return [encode(v) for v in node]
        return node

    packed = {
        "encoding": "lossless-json-subtree-references-v1",
        "shared_content": pool,
        "evidence": encode(value),
        "expanded_sha256": sha(value),
        "decoding": "Replace each single-key {$history_ref: id} object with shared_content[id], recursively. All content is present in this request; no external files are needed.",
    }
    if unpack_history(packed) != value:
        raise RuntimeError("Lossless history verification failed")
    return packed


def unpack_history(packed):
    def decode(node, active=frozenset()):
        if isinstance(node, dict) and set(node) == {"$history_ref"}:
            key = node["$history_ref"]
            if key in active:
                raise ValueError("Cyclic evidence reference")
            return decode(packed["shared_content"][key], active | {key})
        if isinstance(node, dict):
            return {k: decode(v, active) for k, v in node.items()}
        if isinstance(node, list):
            return [decode(v, active) for v in node]
        return node

    result = decode(packed["evidence"])
    if sha(result) != packed["expanded_sha256"]:
        raise ValueError("Evidence content hash mismatch")
    return result


def verify_history(evidence):
    required = [
        "fixed_study_context",
        "instruction_history",
        "execution_history",
        "conclusions_and_faults",
    ]
    if any(not evidence.get(k) for k in required):
        raise ValueError("Incomplete required evidence package")
    history = evidence["instruction_history"]
    versions = history["versions"]
    by_id = {v["version_id"]: v for v in versions}
    if len(by_id) != len(versions):
        raise ValueError("Duplicate instruction version")
    for identifier in [history["original_version"], history["preceding_version"]]:
        if identifier not in by_id:
            raise ValueError("Missing original or preceding instructions")
    for version in versions:
        if (
            not version["instructions"].strip()
            or hashlib.sha256(version["instructions"].encode()).hexdigest() != version["sha256"]
        ):
            raise ValueError("Instruction contents or version hash mismatch")
    attempts = evidence["execution_history"]
    ids = [a["attempt_id"] for a in attempts]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate execution attempt")
    expected = set(evidence["fixed_study_context"]["required_history_attempt_ids"])
    if set(ids) != expected:
        raise ValueError("Execution history coverage mismatch")
    for attempt in attempts:
        if attempt["instruction_version"] not in by_id:
            raise ValueError("Execution refers to missing instructions")
        for key in [
            "request",
            "initial_state",
            "final_state",
            "final_output",
            "business_journal",
            "native_approvals",
            "official_traces",
            "completed_items",
            "controller_operations",
            "correctness_results",
            "metrics",
            "classification",
        ]:
            if key not in attempt:
                raise ValueError("Missing execution evidence: " + key)
        if not attempt["official_traces"] or not attempt["completed_items"]:
            raise ValueError("Missing actual execution traces")
    return {
        "attempt_count": len(ids),
        "instruction_versions": list(by_id),
        "attempt_ids": ids,
        "expanded_sha256": sha(evidence),
        "complete_required_history": True,
    }


def validate_candidate(candidate, evidence):
    history = evidence["instruction_history"]
    preceding = next(
        v["instructions"]
        for v in history["versions"]
        if v["version_id"] == history["preceding_version"]
    )
    if not candidate.rationale.strip():
        raise ValueError("A revision or no-change rationale is required")
    if candidate.status == "insufficient_evidence":
        if candidate.instructions is not None or candidate.changes:
            raise ValueError("Insufficient evidence must not supply a candidate")
        return
    if not candidate.instructions or not candidate.instructions.strip():
        raise ValueError("A complete instruction set is required")
    if candidate.status == "unchanged":
        if candidate.instructions != preceding or candidate.changes:
            raise ValueError("Unchanged means byte-identical instructions and no changes")
        return
    if candidate.instructions == preceding or not candidate.changes:
        raise ValueError("Revised status requires actual explained changes")
    refs = {a["attempt_id"]: set(a["trace_index"]) for a in evidence["execution_history"]}
    for change in candidate.changes:
        if not change.evidence_refs or not change.summary.strip():
            raise ValueError("Each change requires concrete evidence")
        for ref in change.evidence_refs:
            if (
                ref.attempt_id not in refs
                or not ref.trace_refs
                or not set(ref.trace_refs) <= refs[ref.attempt_id]
            ):
                raise ValueError("Candidate cites missing attempt or trace evidence")


def request_arguments(prompt, packed):
    return {
        "model": MODEL,
        "reasoning": {"effort": "high"},
        "instructions": prompt,
        "input": canonical(packed),
        "truncation": "disabled",
        "store": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "InstructionRevision",
                "strict": True,
                "schema": InstructionRevision.model_json_schema(),
            }
        },
    }


async def generate(
    directory, verify_sources, prior_usd, budget_usd, pricing, client_factory=AsyncOpenAI
):
    """One candidate request; persist an ambiguous/invalid attempt without replay."""
    directory = Path(directory)
    state_path = directory / "state.json"
    state = json.loads(state_path.read_text())
    if state["status"] not in ["prepared", "counted", "complete"]:
        raise RuntimeError("Revision attempt unresolved; never automatically regenerate")
    verify_sources()
    args = json.loads((directory / "request.json").read_text())
    if sha(args) != state["request_sha256"]:
        raise RuntimeError("Frozen revision request changed")
    evidence = unpack_history(json.loads(args["input"]))
    coverage = verify_history(evidence)
    if coverage != json.loads((directory / "coverage.json").read_text()):
        raise RuntimeError("Revision payload coverage changed")
    if state["status"] == "complete":
        if file_sha(directory / "candidate.json") != state["candidate_json_sha256"]:
            raise RuntimeError("Saved candidate changed")
        candidate = InstructionRevision.model_validate_json(
            (directory / "candidate.json").read_text()
        )
        validate_candidate(candidate, evidence)
        if (
            candidate.instructions is not None
            and file_sha(directory / "candidate.txt") != state["candidate_text_sha256"]
        ):
            raise RuntimeError("Saved replacement instructions changed")
        return candidate
    async with client_factory(max_retries=0, timeout=600) as client:
        if state["status"] == "prepared":
            # This is a token-count API operation, not an instruction generation.
            count_args = {
                k: copy.deepcopy(args[k])
                for k in ["model", "reasoning", "instructions", "input", "text", "truncation"]
            }
            counted = await client.responses.input_tokens.count(**count_args)
            state.update(status="counted", input_tokens=counted.input_tokens)
            save(directory / "token-count.json", counted.model_dump(mode="json"))
            save(state_path, state)
        native_input = state["input_tokens"]
        if native_input + 8192 + MAX_OUTPUT_TOKENS > CONTEXT_TOKENS:
            raise RuntimeError("Complete history exceeds native context; no generation sent")
        max_input_rate = max(pricing["input"], pricing["cache_read"], pricing["cache_write"])
        reservation = (
            (native_input + 8192) * max_input_rate + MAX_OUTPUT_TOKENS * pricing["output"]
        ) / 1_000_000
        if prior_usd + reservation > budget_usd:
            raise RuntimeError("Revision reservation exceeds remaining shared budget")
        state.update(
            status="generating",
            generation_requests=1,
            reservation_usd=reservation,
            started_at_unix=time.time(),
        )
        save(state_path, state)
        started = time.monotonic()
        try:
            response = await client.responses.create(**args)
            save(directory / "response.json", response.model_dump(mode="json"))
            state["generation_seconds"] = time.monotonic() - started
            if response.usage is None:
                raise RuntimeError("Missing revision usage; retain reservation")
            # Output usage already includes billed reasoning tokens.
            cost = estimate(response.usage.model_dump(), pricing)
            state.update(cost_usd=cost, response_id=response.id, usage=response.usage.model_dump())
            if response.usage.input_tokens > native_input + 8192 or cost > reservation:
                raise RuntimeError("Revision usage exceeded reservation assumptions")
            if response.status != "completed":
                raise RuntimeError("Incomplete revision response: " + response.status)
            candidate = InstructionRevision.model_validate_json(response.output_text)
            validate_candidate(candidate, evidence)
            save(directory / "candidate.json", candidate.model_dump())
            if candidate.instructions is not None:
                (directory / "candidate.txt").write_text(candidate.instructions)
            state.update(
                status="complete",
                candidate_status=candidate.status,
                reservation_usd=0,
                candidate_json_sha256=file_sha(directory / "candidate.json"),
                candidate_text_sha256=file_sha(directory / "candidate.txt")
                if candidate.instructions is not None
                else None,
            )
            save(state_path, state)
            return candidate
        except Exception as exc:
            state.update(
                status="failed_or_unresolved",
                error_type=type(exc).__name__,
                generation_seconds=time.monotonic() - started,
            )
            save(state_path, state)
            raise
