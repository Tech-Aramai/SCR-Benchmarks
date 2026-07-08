"""Plots. Ships `tokens_to_correct` and `correctness_by_model`."""
from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


def _save(fig, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def plot_tokens_to_correct(
    runs: list[dict[str, Any]],
    out_path: Path,
    *,
    sample_type: str = "exact",
) -> Path:
    """Grouped bar chart, x=variant, grouped by model, y=mean total_tokens on
    correct runs of one sample_type.

    Falls back to single-bar layout when only one model is present.
    Saves both PNG and SVG (matplotlib infers from extension).
    """
    filtered = [
        r for r in runs
        if r.get("sample_type") == sample_type
        and r.get("status") == "graded"
        and r.get("correct")
    ]

    fig, ax = plt.subplots(figsize=(9, 5))

    if not filtered:
        ax.text(
            0.5, 0.5,
            f"no correct runs for sample_type={sample_type}",
            ha="center", va="center", transform=ax.transAxes,
        )
        ax.set_axis_off()
        _save(fig, out_path)
        return out_path

    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in filtered:
        buckets[(r["model_id"], r["variant"])].append(r["total_tokens"])

    variants = sorted({v for (_m, v) in buckets.keys()})
    models = sorted({m for (m, _v) in buckets.keys()})

    width = 0.8 / max(len(models), 1)
    x = np.arange(len(variants))

    for i, model in enumerate(models):
        means: list[float] = []
        stdevs: list[float] = []
        ns: list[int] = []
        for v in variants:
            vals = buckets.get((model, v), [])
            ns.append(len(vals))
            means.append(statistics.fmean(vals) if vals else 0.0)
            stdevs.append(statistics.stdev(vals) if len(vals) >= 2 else 0.0)

        offset = (i - (len(models) - 1) / 2) * width
        bars = ax.bar(
            x + offset, means, width,
            yerr=stdevs, capsize=4, label=model,
        )
        for bar, n in zip(bars, ns):
            if n > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    f"n={n}",
                    ha="center", va="bottom", fontsize=8,
                )

    ax.set_xticks(x)
    ax.set_xticklabels(variants)
    ax.set_xlabel("Retrieval variant")
    ax.set_ylabel("Mean total tokens (correct runs)")
    ax.set_title(f"Tokens-to-correct on sample_type={sample_type}")
    if len(models) > 1:
        ax.legend(title="model")

    _save(fig, out_path)
    return out_path


def plot_correctness_by_model(
    runs: list[dict[str, Any]],
    out_path: Path,
) -> Path:
    """Grouped bar chart of correctness rate per (model, variant), one bar set
    per sample_type. Surfaces where a variant fails on hard samples for a given
    model without needing the reader to read prose."""
    by_cell: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    for r in runs:
        if r.get("status") != "graded":
            continue
        key = (r["model_id"], r["variant"], r["sample_type"])
        by_cell[key].append(bool(r.get("correct")))

    sample_types = sorted({k[2] for k in by_cell})
    variants = sorted({k[1] for k in by_cell})
    models = sorted({k[0] for k in by_cell})

    fig, axes = plt.subplots(1, len(sample_types), figsize=(4 * len(sample_types), 4), sharey=True)
    if len(sample_types) == 1:
        axes = [axes]

    width = 0.8 / max(len(models), 1)
    x = np.arange(len(variants))

    for ax, st in zip(axes, sample_types):
        for i, model in enumerate(models):
            rates: list[float] = []
            ns: list[int] = []
            for v in variants:
                vals = by_cell.get((model, v, st), [])
                ns.append(len(vals))
                rates.append(sum(vals) / len(vals) if vals else 0.0)
            offset = (i - (len(models) - 1) / 2) * width
            bars = ax.bar(x + offset, rates, width, label=model)
            for bar, rate, n in zip(bars, rates, ns):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    f"{int(rate*n)}/{n}",
                    ha="center", va="bottom", fontsize=8,
                )
        ax.set_title(st)
        ax.set_xticks(x)
        ax.set_xticklabels(variants)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("Correctness rate")
    if len(models) > 1:
        axes[-1].legend(title="model", loc="lower right")
    fig.suptitle("Correctness by (variant, model) per sample type")

    _save(fig, out_path)
    return out_path
