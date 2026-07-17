"""Matrix iteration: enumerate (sample × variant × model × rep), filter completed,
execute the rest. Persist immediately and atomically."""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import traceback
from pathlib import Path
from typing import Any, Callable

import anthropic

from .config import Config
from .grader import grade
from .persistence import (
    already_done,
    append_manifest,
    make_run_id,
    write_raw_artifact,
)
from .variants import mcp as mcp_variant
from .variants import url as url_variant
from .variants import zip as zip_variant

logger = logging.getLogger(__name__)


VARIANT_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "mcp": mcp_variant.run,
    "url": url_variant.run,
    "zip": zip_variant.run,
}


def _shuffle_payload(payload: Any, seed: int) -> Any:
    """Return a copy of a dict payload with its top-level keys permuted
    deterministically by `seed`. LLMs are order-sensitive (SA-ISR §8), so shuffling
    across reps probes whether behaviour is stable at constant information content.
    Non-dicts (or fewer than 2 keys) are returned unchanged."""
    if not isinstance(payload, dict) or len(payload) < 2:
        return payload
    keys = list(payload.keys())
    random.Random(seed).shuffle(keys)
    return {k: payload[k] for k in keys}


def load_samples(samples_dir: Path, sample_types: list[str]) -> list[dict[str, Any]]:
    """Load every sample JSON whose `type` is in `sample_types`."""
    samples = []
    for path in sorted(samples_dir.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            sample = json.load(f)
        if sample.get("type") in sample_types:
            samples.append(sample)
    return samples


def iter_matrix(cfg: Config, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cartesian product of samples × variants × models × reps."""
    cells = []
    for sample in samples:
        for variant in cfg.variants:
            for model in cfg.models:
                for rep in range(1, cfg.reps_per_model + 1):
                    cells.append({
                        "sample": sample,
                        "variant": variant,
                        "model_id": model.id,
                        "model_alias": model.alias,
                        "rep": rep,
                        "run_id": make_run_id(variant, sample["id"], model.id, rep),
                    })
    return cells


def run_one(
    *,
    cell: dict[str, Any],
    cfg: Config,
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """Execute one matrix cell. Returns the record dict to persist."""
    sample = cell["sample"]
    variant = cell["variant"]
    runner = VARIANT_RUNNERS.get(variant)
    if runner is None:
        return _error_record(cell, cfg, f"unknown variant: {variant}")

    # Field-order shuffle (opt-in via config). Deterministic per rep so runs stay
    # reproducible; the seed is recorded on the run so the ordering is recoverable.
    field_order_seed: int | None = None
    if cfg.shuffle_field_order:
        field_order_seed = int(cell["rep"])
        sample = {**sample, "payload": _shuffle_payload(sample.get("payload"), field_order_seed)}

    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        variant_result = runner(
            client=client,
            cfg=cfg,
            sample=sample,
            model_alias=cell["model_alias"],
        )
    except anthropic.APIError as e:
        return _error_record(cell, cfg, f"{type(e).__name__}: {e}", timestamp)
    except Exception as e:  # noqa: BLE001 — capture and continue
        return _error_record(
            cell,
            cfg,
            f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            timestamp,
        )

    try:
        verdict = grade(
            client=client,
            grader_model=cfg.grader_model,
            sample=sample,
            final_text=variant_result["final_text"],
            universe_description=cfg.universe_description,
        )
        verdict_dict = verdict.model_dump()
        graded_status = "graded"
    except Exception as e:  # noqa: BLE001
        verdict_dict = {
            "predicted_behavior": "error",
            "predicted_schema": None,
            "predicted_candidates": [],
            "cited_id_or_path": None,
            "correct": False,
            "hallucinated": False,
            "notes": f"grader exception: {type(e).__name__}: {e}",
        }
        # Variant call succeeded but grading failed; still persist as ok so the
        # raw artifact is durable and re-grading can rebuild the verdict.
        graded_status = "ok"

    return {
        "run_id": cell["run_id"],
        "status": graded_status,
        "timestamp": timestamp,
        "variant": variant,
        "sample_type": sample.get("type"),
        "sample_id": sample["id"],
        "model_id": cell["model_id"],
        "model_alias_requested": cell["model_alias"],
        "model_resolved": variant_result.get("model_resolved"),
        "rep": cell["rep"],
        "field_order_seed": field_order_seed,
        "temperature": cfg.temperature,
        "input_tokens": variant_result["input_tokens"],
        "output_tokens": variant_result["output_tokens"],
        "total_tokens": variant_result["input_tokens"] + variant_result["output_tokens"],
        "cache_read_input_tokens": variant_result["cache_read_input_tokens"],
        "cache_creation_input_tokens": variant_result["cache_creation_input_tokens"],
        "tool_calls": variant_result["tool_calls"],
        "tools_used": variant_result["tools_used"],
        "turns": variant_result["turns"],
        "wall_seconds": variant_result["wall_seconds"],
        "stop_reason": variant_result["stop_reason"],
        "final_text": variant_result["final_text"],
        "predicted_schema": verdict_dict.get("predicted_schema"),
        "predicted_candidates": verdict_dict.get("predicted_candidates", []),
        "predicted_behavior": verdict_dict.get("predicted_behavior"),
        "cited_id_or_path": verdict_dict.get("cited_id_or_path"),
        "correct": bool(verdict_dict.get("correct", False)),
        "hallucinated": bool(verdict_dict.get("hallucinated", False)),
        "abstained_or_narrowed": verdict_dict.get("predicted_behavior")
            in {"decline", "narrow", "flag_inconsistency"},
        "grader_notes": verdict_dict.get("notes", ""),
        "grader_model": cfg.grader_model,
        # Per-turn tool selection — the URL variant populates it; MCP/ZIP omit.
        "per_turn_tools": variant_result.get("per_turn_tools"),
        "raw_response": variant_result.get("raw_response"),
        "error": None,
    }


def _error_record(
    cell: dict[str, Any],
    cfg: Config,
    error: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": cell["run_id"],
        "status": "error",
        "timestamp": timestamp or dt.datetime.now(dt.timezone.utc).isoformat(),
        "variant": cell["variant"],
        "sample_type": cell["sample"].get("type"),
        "sample_id": cell["sample"]["id"],
        "model_id": cell["model_id"],
        "model_alias_requested": cell["model_alias"],
        "rep": cell["rep"],
        "temperature": cfg.temperature,
        "error": error,
    }


def _apply_filters(cells: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    def keep(c: dict[str, Any]) -> bool:
        if (v := filters.get("variant")) and c["variant"] != v:
            return False
        if (s := filters.get("sample_type")) and c["sample"].get("type") != s:
            return False
        if (m := filters.get("model")) and c["model_id"] != m:
            return False
        if (r := filters.get("rep")) and c["rep"] != r:
            return False
        return True
    return [c for c in cells if keep(c)]


def run_matrix(
    cfg: Config,
    *,
    force: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Run every cell in the matrix that isn't already done. Returns counts."""
    samples = load_samples(cfg.samples_dir, cfg.sample_types)
    if not samples:
        raise RuntimeError(
            f"no samples found in {cfg.samples_dir} for types {cfg.sample_types}"
        )

    cells = iter_matrix(cfg, samples)
    if filters:
        cells = _apply_filters(cells, filters)

    # max_retries: bumped from the SDK's default 2 — a smaller rate-limit pool
    # plus a chatty run (10+ tool turns) can burst 429s that 2 retries can't
    # outlast.
    # timeout: bumped from the SDK's default 600s — the MCP variant on the
    # chimeric sample can take long enough server-side that 10 min isn't enough;
    # 1800s (30 min) is enough headroom.
    client = anthropic.Anthropic(
        api_key=cfg.anthropic_api_key,
        max_retries=8,
        timeout=1800.0,
    )

    counts = {"total": len(cells), "skipped": 0, "ok": 0, "error": 0}
    for cell in cells:
        if not force and already_done(cell["run_id"], cfg.raw_dir):
            counts["skipped"] += 1
            logger.info("skip %s (already done)", cell["run_id"])
            continue

        logger.info("run  %s", cell["run_id"])
        record = run_one(cell=cell, cfg=cfg, client=client)
        write_raw_artifact(record, cfg.raw_dir)

        # Manifest row excludes the bulky raw_response payload.
        manifest_row = {k: v for k, v in record.items() if k != "raw_response"}
        append_manifest(manifest_row, cfg.manifest_path)

        if record["status"] == "error":
            counts["error"] += 1
        else:
            counts["ok"] += 1
    return counts
