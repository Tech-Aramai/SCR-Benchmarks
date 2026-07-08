"""Run identity, atomic writes, manifest append, resume detection."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def make_run_id(variant: str, sample_id: str, model_id: str, rep: int) -> str:
    """Deterministic run ID — same logical run, same ID, every time. No UUIDs,
    no timestamps. This is what makes resume work."""
    return f"{variant}__{sample_id}__{model_id}__rep{rep}"


def artifact_path(run_id: str, raw_dir: Path) -> Path:
    """Resolve a run_id to its on-disk artifact path.

    Layout is `results/raw/{model_family}/{variant}/{run_id}.json` — model
    family is derived from the model_id segment of the run_id (`opus-4-7`
    → `opus`, `haiku-4-5` → `haiku`). This makes per-model and per-variant
    sweeps easy to grep / tar / rsync.
    """
    variant, _sample_id, model_id, _rep = run_id.split("__")
    family = model_id.split("-", 1)[0]
    return raw_dir / family / variant / f"{run_id}.json"


def already_done(run_id: str, raw_dir: Path) -> bool:
    """Done = artifact exists, parses as valid JSON, has non-error status.
    Partial / corrupted artifacts are re-run."""
    path = artifact_path(run_id, raw_dir)
    if not path.exists():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return record.get("status") in {"ok", "graded"}


def write_raw_artifact(record: dict[str, Any], raw_dir: Path) -> Path:
    """Write to {run_id}.json.tmp then rename. tmp.replace(path) is atomic on POSIX
    and effectively atomic on NTFS for same-filesystem renames."""
    final = artifact_path(record["run_id"], raw_dir)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    tmp.replace(final)
    return final


def append_manifest(row: dict[str, Any], manifest_path: Path) -> None:
    """Append + flush + fsync so an OS-level crash doesn't lose the last record."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, default=str)
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
