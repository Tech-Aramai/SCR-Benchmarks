"""Aggregate metrics from runs.jsonl (per-property metrics)."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


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


def tokens_to_correct(
    runs: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, float]]:
    """Mean total_tokens on correct runs, grouped by (model_id, variant, sample_type).

    The model dimension is significant — different model tiers produce very
    different token totals on the same cell, and blending them hides the
    per-model story.
    """
    buckets: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for r in runs:
        if r.get("status") != "graded":
            continue
        if not r.get("correct"):
            continue
        buckets[(r["model_id"], r["variant"], r["sample_type"])].append(r["total_tokens"])

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
