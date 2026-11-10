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


def estimate_range(usage, rates):
    """Bound cost when input could be ordinary input or a cache write."""
    details = usage.get("input_tokens_details") or {}
    writes = details.get("cache_write_tokens")
    unknown = details.get("unclassified_input_tokens")
    if unknown is None:
        unknown = (
            usage["input_tokens"] - (details.get("cached_tokens") or 0) if writes is None else 0
        )
    if unknown < 0:
        raise ValueError("Inconsistent unclassified input usage")
    ordinary = estimate(usage, rates)
    all_writes = estimate(
        {
            **usage,
            "input_tokens_details": {**details, "cache_write_tokens": (writes or 0) + unknown},
        },
        rates,
    )
    return [min(ordinary, all_writes), max(ordinary, all_writes)]
