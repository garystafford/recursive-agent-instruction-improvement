"""Fresh hosted task sessions for the synthetic workflow suite."""

import asyncio
import base64
import copy
import hashlib
import json
import time
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from refund_pilot.workflows import transport
from refund_pilot.workflows.cases import request_text
from refund_pilot.workflows.costs import estimate
from refund_pilot.workflows.qualification import ROOT, read_bundle, save
from refund_pilot.workflows.service import WRITES, approval_decision, catalog

MODEL = "gpt-6.1-sol"


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    outcome: Literal[
        "recommended",
        "purchased",
        "modified",
        "cancelled",
        "replaced",
        "returned",
        "exchanged",
        "refunded",
        "booked",
        "corrected",
        "skipped",
        "updated",
        "ordered",
        "quarantined",
        "notified",
        "reconciled",
        "pending",
        "denied",
        "unchanged",
    ]
    amount_cents: int | None
    references: list[str]


class Final(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    message: str
    results: list[Result]


def configuration(instructions, case):
    content = {
        "refund_pilot/__init__.py": b"",
        "refund_pilot/workflows/__init__.py": b"",
        "refund_pilot/workflows/service.py": (
            ROOT / "refund_pilot/workflows/service.py"
        ).read_bytes(),
        "initial.json": json.dumps(case["initial"]).encode(),
        "requirements-hosted.lock.txt": (ROOT / "requirements-hosted.lock.txt").read_bytes(),
    }
    return {
        "review": "none",
        "metadata": {"study": "retail-instruction-improvement", "task": case["id"]},
        "agent": {
            "model": MODEL,
            "reasoning": {"effort": "low"},
            "service_tier": "default",
            "multi_agent": {"enabled": False},
            "instructions": instructions,
            "text": {
                "format": {
                    "type": "json_schema",
                    "schema": transport.strict_schema(Final.model_json_schema()),
                }
            },
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "retail_workflows",
                    "required": True,
                    "allowed_tools": [t["name"] for t in catalog()],
                    "transport": {
                        "type": "stdio",
                        "command": "/workspace/venv/bin/python",
                        "args": [
                            "-m",
                            "refund_pilot.workflows.service",
                            "serve",
                            "/workspace/business",
                        ],
                        "cwd": "/workspace",
                    },
                },
                {
                    "type": "function",
                    "name": "request_action_approval",
                    "description": "Obtain native automated consent for one exact protected business operation. Supply the exact tool name, target, data_json and idempotency_key you will use. Wait for an approved decision and use the returned approval_id for the MCP business action.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            k: {"type": "string"}
                            for k in ["operation", "target", "data_json", "idempotency_key"]
                        },
                        "required": ["operation", "target", "data_json", "idempotency_key"],
                        "additionalProperties": False,
                    },
                },
            ],
        },
        "environment": {
            "type": "openai_hosted",
            "container_size": "medium",
            "network": {"access": "enabled"},
            "packages": {"python": ["uv==0.9.9"]},
            "files": [
                {
                    "type": "inline",
                    "path": "/workspace/" + name,
                    "data": base64.b64encode(data).decode(),
                }
                for name, data in content.items()
            ],
            "setup_commands": [
                {
                    "cwd": "/workspace",
                    "command": "uv python install 3.14 && uv venv --python 3.14 /workspace/venv && uv pip install --python /workspace/venv/bin/python -r /workspace/requirements-hosted.lock.txt && /workspace/venv/bin/python -m refund_pilot.workflows.service initialize /workspace/business",
                }
            ],
        },
    }


class StreamObserver:
    def __init__(self):
        self.observer = None
        self.stream = None
        self.signal = asyncio.Event()
        self.ready = asyncio.Event()
        self.handled = set()
        self.stream_error = None
        self.items = {}
        self.turns = {}
        self.consumed = set()
        self.pending = []
        self.event_ids = set()

    async def start(self, client, sid, env_id, execution):
        self.client, self.sid, self.env_id = client, sid, env_id
        self.execution = execution
        self.observer = asyncio.create_task(self.observe())
        await asyncio.wait_for(self.ready.wait(), 30)
        if self.stream_error:
            raise RuntimeError(self.stream_error)

    async def close(self):
        if self.observer:
            self.observer.cancel()
            try:
                await self.observer
            except asyncio.CancelledError:
                pass
        if self.stream:
            await self.stream.close()

    def feed(self, data):
        event_id = data.get("event_id")
        if event_id and event_id in self.event_ids:
            return
        if event_id:
            self.event_ids.add(event_id)
        typ = data["type"]
        if typ == "agent.session.turn.item.done":
            item = copy.deepcopy(data["item"])
            item.setdefault("turn_id", data["turn_id"])
            self.items[item["id"]] = item
        elif typ in [
            "agent.session.turn.created",
            "agent.session.turn.completed",
            "agent.session.turn.failed",
            "agent.session.turn.cancelled",
        ]:
            turn = data["turn"]
            if turn.get("subagent_id") is None:
                prior = self.turns.get(turn["id"], {})
                if prior.get("status") not in ["completed", "failed", "cancelled"]:
                    self.turns[turn["id"]] = copy.deepcopy(turn)
        elif typ == "agent.session.requires_action":
            self.pending = copy.deepcopy(data["session"].get("required_actions", []))
        elif typ in ["agent.session.failed", "agent.session.environment.failed", "error"]:
            self.stream_error = "Stream reported failure: " + typ
        self.signal.set()

    async def observe(self):
        try:
            self.stream = await self.client.beta.agents.sessions.events.stream(
                self.sid, timeout=650
            )
            self.ready.set()
            async for event in self.stream:
                data = transport.wire_record(event)
                transport.append(
                    self.execution / "session-events.jsonl",
                    {
                        "received_at_unix": time.time(),
                        "received_monotonic": time.monotonic(),
                        "event": data,
                    },
                )
                self.feed(data)
            self.stream_error = "Session stream closed before further work; reconcile saved state"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- persist and reconcile transport failures
            self.stream_error = str(transport.error_summary(exc))
        finally:
            self.ready.set()
            self.signal.set()

    async def reconcile(self, reason):
        """Only recovery/missing-output fallback reads; never replay input or approval."""
        transport.append(
            self.execution / "stream-fallbacks.jsonl", {"reason": reason, "at_unix": time.time()}
        )
        if self.stream_error:
            if self.observer:
                self.observer.cancel()
                try:
                    await self.observer
                except asyncio.CancelledError:
                    pass
            if self.stream:
                await self.stream.close()
            self.stream_error = None
            self.ready.clear()
            self.observer = asyncio.create_task(self.observe())
            await asyncio.wait_for(self.ready.wait(), 30)
            if self.stream_error:
                raise RuntimeError(self.stream_error)
        session = transport.wire_record(await self.client.beta.agents.sessions.retrieve(self.sid))
        if session["status"] == "failed":
            raise RuntimeError("Session failed during stream recovery")
        self.pending = copy.deepcopy(session.get("required_actions", []))
        for item in await transport.collect(self.client.beta.agents.sessions.items, self.sid):
            if self.items.get(item["id"], {}).get("status") != "completed":
                self.items[item["id"]] = item
        for turn in await transport.collect(self.client.beta.agents.sessions.turns, self.sid):
            if turn.get("subagent_id") is None and self.turns.get(turn["id"], {}).get(
                "status"
            ) not in ["completed", "failed", "cancelled"]:
                self.turns[turn["id"]] = turn


class Controller(StreamObserver):
    def __init__(self, case, pricing, model_allowance):
        super().__init__()
        self.case = case
        self.pricing = pricing
        self.model_allowance = model_allowance
        self.decisions = []

    def budget(self, data):
        if data.get("usage") and estimate(data["usage"], self.pricing) >= self.model_allowance:
            raise RuntimeError("Per-task model allowance reached")

    async def approve(self, action):
        key = (action.get("turn_id"), action.get("call_id"))
        if key in self.handled:
            return
        if action.get("type") != "function_call" or action.get("name") != "request_action_approval":
            raise RuntimeError("Unexpected application function")
        args = action["arguments"]
        args = json.loads(args) if isinstance(args, str) else args
        prefix = "mcp__retail_workflows__"
        operation = args["operation"]
        if operation.startswith(prefix) and operation[len(prefix) :] in WRITES:
            operation = operation[len(prefix) :]
        data = json.loads(args["data_json"])
        if not isinstance(data, dict):
            raise TypeError("Approval arguments must encode an object")
        aid = "approval-" + hashlib.sha256(key[1].encode()).hexdigest()[:24]
        decision = approval_decision(
            self.case["initial"],
            operation,
            args["target"],
            data,
            args["idempotency_key"],
            aid,
        )
        # Verify the request is still pending before providing consent.
        observed = transport.wire_record(await self.client.beta.agents.sessions.retrieve(self.sid))
        if not any(
            (a.get("turn_id"), a.get("call_id")) == key
            for a in observed.get("required_actions", [])
        ):
            raise RuntimeError("Approval request is no longer pending")
        if decision["decision"] == "approved":
            await self.client.beta.agents.environments.files.create(
                self.env_id,
                path=f"/workspace/business/approvals/{aid}.json",
                type="inline",
                data=base64.b64encode(json.dumps(decision).encode()).decode(),
            )
        entry = {"turn_id": key[0], "call_id": key[1], **decision}
        self.decisions.append(entry)
        save(self.execution / "native-approvals.json", self.decisions)
        await transport.submit_event(
            self.client.beta.agents.sessions,
            self.sid,
            {
                "type": "agent.session.input.tool_result",
                "turn_id": key[0],
                "call_id": key[1],
                "success": True,
                "output": json.dumps(decision),
            },
            "workflow-approval-" + key[1],
            self.execution,
        )
        self.handled.add(key)

    async def wait_final(self):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            self.signal.clear()
            for tid, turn in self.turns.items():
                if turn["status"] in ["failed", "cancelled"]:
                    raise RuntimeError("Task turn " + turn["status"])
                if turn["status"] == "completed":
                    finals = [
                        i
                        for i in self.items.values()
                        if i.get("turn_id") == tid
                        and i.get("type") == "message"
                        and i.get("phase") == "final_answer"
                        and i.get("status") == "completed"
                    ]
                    if len(finals) == 1:
                        text = "".join(
                            c["text"] for c in finals[0]["content"] if c["type"] == "output_text"
                        )
                        self.consumed.add(tid)
                        try:
                            return Final.model_validate_json(text).model_dump(), tid
                        except ValidationError:
                            return {"invalid_final_text": text}, tid
            if self.pending:
                observed = transport.wire_record(
                    await self.client.beta.agents.sessions.retrieve(self.sid)
                )
                self.budget(observed)
                self.pending = []
                for action in observed.get("required_actions", []):
                    await self.approve(action)
                continue
            if self.stream_error:
                await self.reconcile("stream recovery; never replay task input")
                continue
            try:
                await asyncio.wait_for(
                    self.signal.wait(), min(5, max(0.01, deadline - time.monotonic()))
                )
            except TimeoutError:
                pass
        raise TimeoutError("Task exceeded 600 seconds")


async def download(client, sid, turn_id, target):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        artifacts = [
            transport.wire_record(a)
            async for a in client.beta.agents.sessions.artifacts.list(sid, limit=100)
        ]
        save(target / "artifact-index.json", artifacts)
        selected = [
            a
            for a in artifacts
            if a["turn_id"] == turn_id and a["path"] == "/workspace/outputs/evidence.zip"
        ]
        if selected:
            blob = await client.beta.agents.sessions.artifacts.content(
                selected[-1]["id"], session_id=sid
            )
            (target / "evidence.zip").write_bytes(blob.content)
            return read_bundle(target / "evidence.zip")
        await asyncio.sleep(1)
    raise RuntimeError("Completed-task artifact unavailable; no task replay")


def metrics(traces, journal, approvals, pricing):
    spans = [
        s
        for row in traces
        for resource in row["otlp"].get("resourceSpans", [])
        for scope in resource.get("scopeSpans", [])
        for s in scope["spans"]
    ]
    unique = {s["spanId"]: s for s in spans}.values()
    generations = sum(s["name"].startswith("chat ") for s in unique)
    usage = transport.trace_usage(traces)
    cost = estimate(usage, pricing)
    return {
        "llm_calls": generations,
        "business_tool_calls": len(journal),
        "approval_calls": len(approvals),
        "tool_calls": len(journal) + len(approvals),
        "usage": usage,
        "estimated_task_model_usd": cost,
    }


async def task(target, case, instructions, pricing, model_allowance):
    target.mkdir(exist_ok=False)
    timer = transport.Timing(target)
    controller = Controller(case, pricing, model_allowance)
    config = configuration(instructions, case)
    save(target / "session-request.json", config)
    record = {
        "id": case["id"],
        "name": case["name"],
        "description": case["description"],
        "case": case,
        "error": None,
        "final": None,
        "status": "attempted",
        "llm_calls": None,
        "tool_calls": None,
        "business_tool_calls": None,
        "approval_calls": None,
        "task_seconds": None,
    }
    sid = None
    setup_start = time.monotonic()
    async with AsyncOpenAI(max_retries=0, timeout=120) as raw:
        client = transport.Measured(raw, timer)
        try:
            session = await client.beta.agents.sessions.create(**config)
            sid, env_id = session.id, session.environment.id
            record.update(session_id=sid, environment_id=env_id)
            save(target / "session-created.json", transport.wire_record(session))
            effective = transport.wire_record(session)["agent"]
            if (
                effective["model"] != MODEL
                or effective["reasoning"]["effort"] != "low"
                or effective["instructions"] != config["agent"]["instructions"]
            ):
                raise RuntimeError("Effective task model, reasoning or instructions differ")
            while True:
                environment = await client.beta.agents.environments.retrieve(env_id)
                save(target / "environment.json", transport.wire_record(environment))
                if environment.status == "connected":
                    break
                if environment.status == "failed" or time.monotonic() - setup_start > 360:
                    raise RuntimeError("Hosted setup failed or timed out")
                await asyncio.sleep(1)
            await controller.start(client, sid, env_id, target)
            record["setup_seconds"] = time.monotonic() - setup_start
            with timer.in_phase("task"):
                started = time.monotonic()
                await transport.submit_event(
                    client.beta.agents.sessions,
                    sid,
                    {
                        "type": "agent.session.input.message",
                        "input": [transport.message(request_text(case))],
                    },
                    "workflow-initial-" + case["id"],
                    target,
                )
                record["final"], turn_id = await controller.wait_final()
                record["task_seconds"] = time.monotonic() - started
            print(
                json.dumps(
                    {
                        "event": "task_finished",
                        "id": case["id"],
                        "task_seconds": record["task_seconds"],
                        "approval_calls": len(controller.decisions),
                    }
                ),
                flush=True,
            )
            with timer.in_phase("evidence"):
                bundle = await download(client, sid, turn_id, target)
                if bundle["initial-state"] != case["initial"]:
                    raise RuntimeError("Hosted initial state differs from frozen case")
                record.update(
                    state=bundle["state"],
                    journal=bundle["journal"],
                    approvals=bundle["approvals"],
                    write_tools=list(WRITES),
                    native_approvals=controller.decisions,
                )
                artifact_index = json.loads((target / "artifact-index.json").read_text())
                record["artifact_paths"] = [entry["path"] for entry in artifact_index]
                save(target / "business-evidence.json", record)
                # Traces may publish after artifacts; these are reads only, outside task timing.
                for attempt in range(61):
                    rows = await transport.collect(client.beta.agents.sessions.traces, sid)
                    save(target / "official-traces.json", rows)
                    spans = [
                        s
                        for t in rows
                        for r in t["otlp"].get("resourceSpans", [])
                        for sc in r.get("scopeSpans", [])
                        for s in sc["spans"]
                    ]
                    if (
                        turn_id in {t["id"] for t in rows}
                        and spans
                        and all(s.get("endTimeUnixNano") for s in spans)
                    ):
                        break
                    if attempt % 6 == 0:
                        print(
                            json.dumps(
                                {
                                    "event": "waiting_for_traces",
                                    "id": case["id"],
                                    "attempt": attempt,
                                }
                            ),
                            flush=True,
                        )
                    await asyncio.sleep(10)
                else:
                    raise RuntimeError("Trace publication incomplete; preserve session")
                save(
                    target / "traces.otlp.json",
                    {
                        "resourceSpans": [
                            r for t in rows for r in t["otlp"].get("resourceSpans", [])
                        ]
                    },
                )
                record.update(metrics(rows, record["journal"], controller.decisions, pricing))
                save(
                    target / "server-items.json",
                    await transport.collect(client.beta.agents.sessions.items, sid),
                )
                observed = transport.wire_record(await client.beta.agents.sessions.retrieve(sid))
                save(target / "session-final.json", observed)
                record["status"] = "completed"
            with timer.in_phase("cleanup"):
                deleted = transport.wire_record(await client.beta.agents.sessions.delete(sid))
                save(target / "cleanup.json", deleted)
                record["session_deleted"] = bool(deleted.get("deleted"))
                if not record["session_deleted"]:
                    raise RuntimeError("Hosted session deletion unverified")
        except Exception as exc:  # noqa: BLE001 -- preserve attempt, never retry a task
            record["error"] = {**transport.error_summary(exc), "message": str(exc)}
            record["status"] = "incomplete"
            if sid:
                try:
                    observed = transport.wire_record(
                        await client.beta.agents.sessions.retrieve(sid)
                    )
                    save(target / "recovery-session.json", observed)
                    if observed["status"] not in ["idle", "failed"]:
                        await transport.submit_event(
                            client.beta.agents.sessions,
                            sid,
                            {"type": "agent.session.input.cancel"},
                            "workflow-stop-" + case["id"],
                            target,
                        )
                except Exception as cleanup_error:  # noqa: BLE001
                    record["recovery_error"] = transport.error_summary(cleanup_error)
        finally:
            await controller.close()
            record["full_run_seconds"] = time.monotonic() - setup_start
            save(target / "result.json", record)
    return record
