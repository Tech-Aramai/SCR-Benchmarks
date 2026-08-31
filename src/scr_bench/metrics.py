"""Aggregate metrics from runs.jsonl (per-property metrics)."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

# Prompt-cache billing multipliers, relative to the model's base input rate:
# a cache write costs 1.25x, a cache read 0.1x. (Anthropic prompt caching,
# checked 2026-09-01.)
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

# List price in USD per 1M tokens, as (input, output). Keyed by our `model_id`,
# not the API alias. Checked 2026-09-01; update alongside any model added to
# config.yaml, and note that a stale entry silently skews `cost_usd` only —
# `billed_tokens` is price-independent.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "opus-4-7": (5.00, 25.00),
    "sonnet-4-6": (3.00, 15.00),
    "haiku-4-5": (1.00, 5.00),
}


def load_runs(manifest_path: Path) -> list[dict[str, Any]]:
    """Load every JSONL line from the manifest."""
    if not manifest_path.exists():
        return []
    runs = []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            runs.append(json.loads(line))
    return runs


def _tok(run: dict[str, Any], key: str) -> int:
    """Token field as an int, treating missing/None (error rows) as 0."""
    return run.get(key) or 0


def in_out_tokens(run: dict[str, Any]) -> int:
    """Uncached input + output only — the run record's `total_tokens` field.

    This UNDERSTATES what a run consumed whenever prompt caching is in play. It
    is kept as a named metric so the older published figures remain reproducible,
    but `billed_tokens` is the honest cost comparison.
    """
    return _tok(run, "input_tokens") + _tok(run, "output_tokens")


def billed_tokens(run: dict[str, Any]) -> int:
    """Every token the API billed for this run, cache traffic included.

    The MCP variant runs its tool-use loop server-side, and essentially all of
    that traffic is billed as cache reads/writes rather than as `input_tokens`.
    Counting only input+output therefore credits MCP for work it actually paid
    for. Derived from the component fields, so it applies retroactively to runs
    recorded before this metric existed.
    """
    return (
        _tok(run, "input_tokens")
        + _tok(run, "output_tokens")
        + _tok(run, "cache_read_input_tokens")
        + _tok(run, "cache_creation_input_tokens")
    )


def cost_usd(run: dict[str, Any]) -> float | None:
    """Price-weighted cost of a run, or None if the model has no price entry.

    Token counts alone overstate the weight of cache traffic, which bills at a
    fraction of the base input rate. This is the number the "variant X is
    cheaper" claim actually rests on.
    """
    price = MODEL_PRICING.get(run.get("model_id", ""))
    if price is None:
        return None
    input_rate, output_rate = price
    return (
        _tok(run, "input_tokens") * input_rate
        + _tok(run, "cache_creation_input_tokens") * input_rate * CACHE_WRITE_MULTIPLIER
        + _tok(run, "cache_read_input_tokens") * input_rate * CACHE_READ_MULTIPLIER
        + _tok(run, "output_tokens") * output_rate
    ) / 1_000_000


# Selectable cost metrics. `billed` is the default everywhere; `in_out` exists to
# reproduce the pre-2026-09 figures.
COST_METRICS: dict[str, Callable[[dict[str, Any]], float | None]] = {
    "billed": billed_tokens,
    "in_out": in_out_tokens,
    "cost": cost_usd,
}

METRIC_LABELS = {
    "billed": "Mean billed tokens, cache included (correct runs)",
    "in_out": "Mean input+output tokens, cache excluded (correct runs)",
    "cost": "Mean cost USD (correct runs)",
}


def tokens_to_correct(
    runs: list[dict[str, Any]],
    *,
    metric: str = "billed",
) -> dict[tuple[str, str, str], dict[str, float]]:
    """Mean cost of a correct run, grouped by (model_id, variant, sample_type).

    `metric` selects what "cost" means — see COST_METRICS. Defaults to `billed`,
    which counts cache traffic; pass `in_out` to reproduce the older numbers.

    The model dimension is significant — different model tiers produce very
    different token totals on the same cell, and blending them hides the
    per-model story.
    """
    try:
        fn = COST_METRICS[metric]
    except KeyError:
        raise ValueError(
            f"unknown metric {metric!r}; expected one of {sorted(COST_METRICS)}"
        ) from None

    buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for r in runs:
        if r.get("status") != "graded":
            continue
        if not r.get("correct"):
            continue
        value = fn(r)
        if value is None:  # unpriced model under metric="cost"
            continue
        buckets[(r["model_id"], r["variant"], r["sample_type"])].append(value)

    result: dict[tuple[str, str, str], dict[str, float]] = {}
    for key, values in buckets.items():
        result[key] = {
            "mean": statistics.fmean(values) if values else 0.0,
            "n": len(values),
            "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
        }
    return result


def status_summary(runs: list[dict[str, Any]]) -> dict[str, int]:
    """Count rows by status (`ok`, `graded`, `error`, ...)."""
    counts: dict[str, int] = defaultdict(int)
    for r in runs:
        counts[r.get("status", "unknown")] += 1
    return dict(counts)


def matrix_coverage(
    runs: list[dict[str, Any]],
) -> dict[tuple[str, str, str], int]:
    """Count successful rows per (sample_type, variant, model_id)."""
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in runs:
        if r.get("status") not in {"ok", "graded"}:
            continue
        key = (r.get("sample_type"), r.get("variant"), r.get("model_id"))
        counts[key] += 1
    return dict(counts)
