"""Shared hosted session transport and timing helpers."""

import asyncio
import contextvars
import json
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from openai import APIConnectionError, APITimeoutError


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value) + "\n")


def message(content):
    return {"role": "user", "content": [{"type": "input_text", "text": content}]}


def wire_record(value):
    """Use API field names, including schema rather than Pydantic's schema_."""
    return value.model_dump(mode="json", by_alias=True)


async def submit_event(sessions, session_id, event, key, directory):
    """Retry only idempotent event delivery, never model execution or local effects."""
    for attempt in range(3):
        try:
            return await sessions.events.create(session_id, events=[event], idempotency_key=key)
        except (APIConnectionError, APITimeoutError) as exc:
            append(
                directory / "event-delivery-retries.jsonl",
                {
                    "idempotency_key": key,
                    "event_type": event["type"],
                    "attempt": attempt + 1,
                    "error": error_summary(exc),
                },
            )
            if attempt == 2:
                raise
            await asyncio.sleep(attempt + 1)


async def collect(resource, session_id):
    return [wire_record(item) async for item in resource.list(session_id, order="asc", limit=100)]


def error_summary(exc: BaseException) -> dict:
    result = {"type": type(exc).__name__}
    if isinstance(exc, BaseExceptionGroup):
        result["children"] = [error_summary(x) for x in exc.exceptions]
    elif exc.__cause__ is not None:
        result["cause"] = error_summary(exc.__cause__)
    for name in ("status_code", "code", "request_id"):
        value = getattr(exc, name, None)
        if isinstance(value, (int, str)):
            result[name] = value
    return result


class Timing:
    def __init__(self, directory):
        self.directory = directory
        self.phase = contextvars.ContextVar("phase", default="setup")

    @contextmanager
    def in_phase(self, name):
        token = self.phase.set(name)
        try:
            yield
        finally:
            self.phase.reset(token)

    def record(self, operation, start, wall, phase, error=None):
        append(
            self.directory / "operation-timing.jsonl",
            {
                "operation": operation,
                "phase": phase,
                "started_monotonic": start,
                "ended_monotonic": time.monotonic(),
                "started_at_unix": wall,
                "seconds": time.monotonic() - start,
                "error_type": type(error).__name__ if error else None,
            },
        )

    async def call(self, operation, function, *args, **kwargs):
        start, wall, phase = time.monotonic(), time.time(), self.phase.get()
        error = None
        try:
            return await function(*args, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.record(operation, start, wall, phase, error)


class Measured:
    """Time SDK operations, including complete pagination, without recording secret arguments."""

    def __init__(self, value, timing, path="client"):
        self.value, self.timing, self.path = value, timing, path

    def __getattr__(self, name):
        value = getattr(self.value, name)
        path = self.path + "." + name
        if callable(value):
            if name == "list":

                async def pages(*args, **kwargs):
                    start, wall, phase = time.monotonic(), time.time(), self.timing.phase.get()
                    error = None
                    try:
                        async for item in value(*args, **kwargs):
                            yield item
                    except BaseException as exc:
                        error = exc
                        raise
                    finally:
                        self.timing.record(path, start, wall, phase, error)

                return pages

            async def invoke(*args, **kwargs):
                return await self.timing.call(path, value, *args, **kwargs)

            return invoke
        return Measured(value, self.timing, path)


def trace_spans(rows):
    return {
        span["spanId"]: span
        for row in rows
        for resource in row["otlp"].get("resourceSpans", [])
        for scope in resource.get("scopeSpans", [])
        for span in scope["spans"]
    }.values()


def trace_usage(rows):
    def attrs(s):
        return {a["key"]: next(iter(a["value"].values())) for a in s.get("attributes", [])}

    agents = [
        a for a in map(attrs, trace_spans(rows)) if a.get("gen_ai.operation.name") == "invoke_agent"
    ]
    if not agents or any(
        "gen_ai.usage.input_tokens" not in a or "gen_ai.usage.output_tokens" not in a
        for a in agents
    ):
        raise ValueError("Root agent token usage is unavailable")
    read_key = "gen_ai.usage.cache_read.input_tokens"
    write_key = "gen_ai.usage.cache_write.input_tokens"
    return {
        "input_tokens": sum(int(a.get("gen_ai.usage.input_tokens", 0)) for a in agents),
        "output_tokens": sum(int(a.get("gen_ai.usage.output_tokens", 0)) for a in agents),
        "input_tokens_details": {
            "cached_tokens": sum(int(a.get(read_key, 0)) for a in agents),
            "cache_write_tokens": sum(int(a.get(write_key) or 0) for a in agents),
            "unclassified_input_tokens": sum(
                int(a["gen_ai.usage.input_tokens"]) - int(a.get(read_key, 0))
                for a in agents
                if a.get(write_key) is None
            ),
        },
    }


def strict_schema(schema: dict) -> dict:
    """Close every object and require every property in these mandatory-argument contracts."""
    result = deepcopy(schema)

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result
