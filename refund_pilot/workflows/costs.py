"""Estimate text model charges from disjoint token categories."""


def estimate(usage, rates):
    details = usage.get("input_tokens_details") or {}
    read = details.get("cached_tokens") or 0
    write = details.get("cache_write_tokens") or 0
    ordinary = usage["input_tokens"] - read - write
    output = usage["output_tokens"]
    if min(ordinary, read, write, output) < 0:
        raise ValueError("Inconsistent token usage")
    return (
        ordinary * rates["input"]
        + read * rates["cache_read"]
        + write * rates["cache_write"]
        + output * rates["output"]
    ) / 1_000_000
