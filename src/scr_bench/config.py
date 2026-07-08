"""Configuration loading.

Three layers:
- `.env`               — secrets (API key, MCP server URL + token).
- `config.yaml`        — global matrix defaults (models, reps, variants, ...).
- `corpora/<name>/corpus.yaml` — corpus-specific settings (schema sources, the
  MCP project id, universe description); may override any matrix default.

All corpus inputs/outputs are rooted at the corpus directory, so each corpus is
self-contained: `corpora/<name>/{samples,schemas-zip,fixtures/zip,results}`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class ModelConfig:
    id: str       # short id used in run_id (e.g. "opus-4-7")
    alias: str    # what we send to the API


@dataclass(frozen=True)
class ZipSource:
    dir: str      # subdirectory under the corpus's fixtures/zip/
    label: str    # human-readable name shown to the model


@dataclass(frozen=True)
class CorpusSources:
    url: list[str]              # repository URLs for the url variant
    zip: list[ZipSource]        # extracted schema sets for the zip variant


@dataclass(frozen=True)
class Config:
    # --- matrix (global defaults; a corpus may override) ---
    models: list[ModelConfig]
    grader_model: str
    reps_per_model: int
    max_tokens: int
    temperature: float
    variants: list[str]
    sample_types: list[str]

    # --- corpus identity ---
    corpus_name: str
    corpus_dir: Path
    universe_description: str
    sources: CorpusSources
    mcp_project_id: str

    # --- secrets (from .env) ---
    anthropic_api_key: str
    mcp_server_url: str
    mcp_token: str

    # Corpus-rooted paths — every input and output lives under corpus_dir.
    @property
    def samples_dir(self) -> Path:
        return self.corpus_dir / "samples"

    @property
    def schemas_zip_dir(self) -> Path:
        return self.corpus_dir / "schemas-zip"

    @property
    def zip_root(self) -> Path:
        return self.corpus_dir / "fixtures" / "zip"

    @property
    def output_dir(self) -> Path:
        return self.corpus_dir / "results"

    @property
    def raw_dir(self) -> Path:
        return self.output_dir / "raw"

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "runs.jsonl"

    @property
    def csv_path(self) -> Path:
        return self.output_dir / "runs.csv"

    @property
    def plots_dir(self) -> Path:
        return self.output_dir / "plots"


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return val


def load_config(
    corpus: str,
    *,
    config_path: Path = Path("config.yaml"),
    corpora_root: Path = Path("corpora"),
) -> Config:
    """Load global defaults + the named corpus's config into one Config.

    `corpus` is a directory name under `corpora_root` (e.g. "nf-htan").
    """
    load_dotenv()  # populates os.environ from .env if present (no-op otherwise)

    with open(config_path) as f:
        global_cfg: dict[str, Any] = yaml.safe_load(f) or {}

    corpus_dir = corpora_root / corpus
    corpus_path = corpus_dir / "corpus.yaml"
    if not corpus_path.exists():
        raise RuntimeError(
            f"Corpus config not found: {corpus_path}. "
            f"Expected corpora/<name>/corpus.yaml. "
            f"Available: {_list_corpora(corpora_root)}"
        )
    with open(corpus_path) as f:
        corpus_cfg: dict[str, Any] = yaml.safe_load(f) or {}

    # Matrix values: corpus overrides global.
    def matrix(key: str) -> Any:
        if key in corpus_cfg:
            return corpus_cfg[key]
        if key in global_cfg:
            return global_cfg[key]
        raise RuntimeError(f"Missing required config key {key!r} in {config_path} or {corpus_path}")

    models = [ModelConfig(id=m["id"], alias=m["alias"]) for m in matrix("models")]
    variants = list(matrix("variants"))

    # Corpus sources.
    sources_raw = corpus_cfg.get("sources", {}) or {}
    url_sources = list(sources_raw.get("url", []) or [])
    zip_sources = [
        ZipSource(dir=z["dir"], label=z["label"])
        for z in (sources_raw.get("zip", []) or [])
    ]
    mcp_raw = sources_raw.get("mcp", {}) or {}
    mcp_project_id = str(mcp_raw.get("project_id", "") or "").strip()

    universe_description = str(corpus_cfg.get("universe_description", "") or "").strip()
    if not universe_description:
        raise RuntimeError(f"{corpus_path} must set `universe_description`.")

    # Secrets. The MCP connector is only needed when the mcp variant is in scope,
    # so we only require its env vars (and project_id) then.
    anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
    if "mcp" in variants:
        mcp_server_url = _require_env("MCP_SERVER_URL")
        mcp_token = _require_env("MCP_TOKEN")
        if not mcp_project_id:
            raise RuntimeError(
                f"{corpus_path} uses the mcp variant but sets no "
                f"`sources.mcp.project_id`."
            )
    else:
        mcp_server_url = os.environ.get("MCP_SERVER_URL", "").strip()
        mcp_token = os.environ.get("MCP_TOKEN", "").strip()

    return Config(
        models=models,
        grader_model=matrix("grader_model"),
        reps_per_model=int(matrix("reps_per_model")),
        max_tokens=int(matrix("max_tokens")),
        temperature=float(matrix("temperature")),
        variants=variants,
        sample_types=list(matrix("sample_types")),
        corpus_name=str(corpus_cfg.get("name") or corpus),
        corpus_dir=corpus_dir,
        universe_description=universe_description,
        sources=CorpusSources(url=url_sources, zip=zip_sources),
        mcp_project_id=mcp_project_id,
        anthropic_api_key=anthropic_api_key,
        mcp_server_url=mcp_server_url,
        mcp_token=mcp_token,
    )


def _list_corpora(corpora_root: Path) -> list[str]:
    if not corpora_root.exists():
        return []
    return sorted(
        p.name for p in corpora_root.iterdir()
        if (p / "corpus.yaml").exists()
    )
