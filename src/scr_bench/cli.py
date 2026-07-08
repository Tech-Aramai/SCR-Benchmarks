"""scr-bench CLI. Commands: check, run, status, report."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from .config import load_config
from .metrics import load_runs, matrix_coverage, status_summary, tokens_to_correct
from .plots import plot_correctness_by_model, plot_tokens_to_correct
from .runner import iter_matrix, load_samples, run_matrix


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scr-bench", description="SCR Benchmark Harness")
    p.add_argument(
        "--corpus",
        required=True,
        help="Corpus to operate on: a directory name under corpora/ (e.g. nf-htan).",
    )
    p.add_argument("--config", type=Path, default=Path("config.yaml"),
                   help="Global matrix config (default: config.yaml).")
    p.add_argument("--corpora-root", type=Path, default=Path("corpora"),
                   help="Directory holding the corpora (default: corpora).")
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="Validate env + config + samples (smoke test)")

    p_run = sub.add_parser(
        "run",
        help="Run experiments. Idempotent: skips runs whose artifact already exists.",
    )
    p_run.add_argument("--variant", help="Restrict to one variant (mcp|url|zip)")
    p_run.add_argument("--sample-type", dest="sample_type",
                       help="Restrict to one sample type (exact|ambiguous|foreign|chimeric)")
    p_run.add_argument("--model", help="Restrict to one model_id (e.g. opus-4-7)")
    p_run.add_argument("--rep", type=int, help="Restrict to one rep index")
    p_run.add_argument("--force", action="store_true",
                       help="Re-run even if artifact exists (use sparingly)")

    sub.add_parser("status", help="Show coverage of the matrix")

    sub.add_parser("report", help="Emit runs.csv and plots from runs.jsonl")

    return p


def _build_filters(args: argparse.Namespace) -> dict[str, str | int]:
    filters: dict[str, str | int] = {}
    for key in ("variant", "sample_type", "model", "rep"):
        val = getattr(args, key, None)
        if val is not None:
            filters[key] = val
    return filters


def _csv_value(v: object) -> object:
    """Stringify list/dict for CSV; passthrough scalars."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, default=str)
    return v


def _cmd_check(cfg) -> int:
    print("corpus:")
    print(f"  name:           {cfg.corpus_name}")
    print(f"  dir:            {cfg.corpus_dir}")
    print(f"  universe:       {cfg.universe_description}")
    print(f"  url sources:    {cfg.sources.url}")
    print(f"  zip sources:    {[z.dir for z in cfg.sources.zip]}")
    print(f"  mcp project_id: {cfg.mcp_project_id or '(none)'}")
    print()
    print("config:")
    print(f"  output_dir:     {cfg.output_dir}")
    print(f"  samples_dir:    {cfg.samples_dir}")
    print(f"  variants:       {cfg.variants}")
    print(f"  sample_types:   {cfg.sample_types}")
    print(f"  models:         {[m.id for m in cfg.models]}")
    print(f"  grader_model:   {cfg.grader_model}")
    print(f"  reps_per_model: {cfg.reps_per_model}")
    print()
    print("env:")
    print(f"  ANTHROPIC_API_KEY: {'set' if cfg.anthropic_api_key else 'MISSING'}")
    if "mcp" in cfg.variants:
        print(f"  MCP_SERVER_URL:    {cfg.mcp_server_url}")
        print(f"  MCP_TOKEN:         {'set' if cfg.mcp_token else 'MISSING'}")
    print()

    samples = load_samples(cfg.samples_dir, cfg.sample_types)
    print(f"samples found: {len(samples)} ({[s['id'] for s in samples]})")

    cells = iter_matrix(cfg, samples)
    print(f"total runs in matrix: {len(cells)}")
    return 0


def _cmd_run(cfg, args) -> int:
    filters = _build_filters(args)
    counts = run_matrix(cfg, force=args.force, filters=filters)
    print("\nrun summary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    return 0 if counts.get("error", 0) == 0 else 1


def _cmd_status(cfg) -> int:
    runs = load_runs(cfg.manifest_path)
    print(f"manifest: {cfg.manifest_path} ({len(runs)} rows)")
    print("\nstatus counts:")
    for k, v in sorted(status_summary(runs).items()):
        print(f"  {k}: {v}")

    print("\nmatrix coverage (sample_type, variant, model):")
    cov = matrix_coverage(runs)
    expected = cfg.reps_per_model
    if not cov:
        print("  (none)")
    for key, n in sorted(cov.items()):
        marker = "OK " if n >= expected else "..."
        print(f"  {marker} {key}: {n}/{expected}")
    return 0


def _cmd_report(cfg) -> int:
    runs = load_runs(cfg.manifest_path)
    if not runs:
        print(f"no runs in {cfg.manifest_path} — run `scr-bench run` first")
        return 1

    cfg.csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({k for r in runs for k in r.keys()})
    with open(cfg.csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in runs:
            writer.writerow({k: _csv_value(r.get(k)) for k in fieldnames})
    print(f"wrote {cfg.csv_path} ({len(runs)} rows)")

    sample_types_in_runs = sorted(
        {r.get("sample_type") for r in runs if r.get("sample_type")}
    )
    for st in sample_types_in_runs:
        out = cfg.plots_dir / f"tokens_to_correct__{st}.png"
        plot_tokens_to_correct(runs, out, sample_type=st)
        print(f"wrote {out} (and .svg sibling)")

    correctness_out = cfg.plots_dir / "correctness_by_model.png"
    plot_correctness_by_model(runs, correctness_out)
    print(f"wrote {correctness_out} (and .svg sibling)")

    print("\ntokens_to_correct (correct runs only):")
    stats = tokens_to_correct(runs)
    if not stats:
        print("  (no correct runs yet)")
    for (model_id, variant, sample_type), s in sorted(stats.items()):
        print(
            f"  {model_id:10s} {variant:6s} {sample_type:12s} "
            f"mean={s['mean']:.0f} stdev={s['stdev']:.0f} n={s['n']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = load_config(
        args.corpus,
        config_path=args.config,
        corpora_root=args.corpora_root,
    )

    if args.cmd == "check":
        return _cmd_check(cfg)
    if args.cmd == "run":
        return _cmd_run(cfg, args)
    if args.cmd == "status":
        return _cmd_status(cfg)
    if args.cmd == "report":
        return _cmd_report(cfg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
