# SCR Benchmark Harness

A small Python harness that benchmarks three **retrieval surfaces** for delivering
JSON Schema context to a language model on a **schema-identification** task, and
measures token usage and answer behavior across repeated runs.

Given a JSON data sample, the model must identify which schema in scope best
describes it — committing to one schema, narrowing to candidates, declining when
nothing matches, or flagging an inconsistency when the sample mixes schemas. The
harness runs each sample through every retrieval surface and model tier, grades
the answers with an LLM-as-judge, and emits the data + plots.

## Retrieval variants

| Variant | How the model gets the schemas |
| --- | --- |
| `mcp` | A graph MCP server traverses a typed schema graph at runtime; the API handles the server-side tool-use loop. |
| `url` | Public GitHub URLs via `web_search` + `web_fetch` (server-side) plus a sandboxed `run_bash` (client-side). |
| `zip` | Schemas extracted to a local directory; the model reads them via a sandboxed, network-blocked `run_bash`. |

All variants share the same model, `max_tokens`, and system prompt. Only the tool
surface and the prompt body differ.

## Corpora

The benchmark is **corpus-parameterized**. A *corpus* is a self-contained
schema collection with its own samples, schema snapshots, config, and results,
living under `corpora/<name>/`. You choose one per run with `--corpus <name>`.

The reference corpus, **`nf-htan`**, targets two public, open JSON Schema
collections:

- [`ncihtan/htan2-data-model`](https://github.com/ncihtan/htan2-data-model) (HTAN2 JSON Schemas)
- [`nf-osi/nf-metadata-dictionary`](https://github.com/nf-osi/nf-metadata-dictionary) (NF-OSI registered JSON schemas)

Each corpus directory is laid out like this:

```
corpora/nf-htan/
  corpus.yaml        # schema sources, MCP project id, universe description, overrides
  samples/*.json     # input samples + their `expected` grading blocks
  schemas-zip/*.zip  # pinned snapshots for the zip variant
  fixtures/zip/      # extracted snapshots (gitignored; regenerate from schemas-zip)
  results/           # runs.jsonl, runs.csv, raw/, plots/ (committed)
  SUMMARY.md         # results write-up for this corpus
```

Samples are corpus-bound (they encode the target schema's field names), so a new
corpus needs its own `samples/` — they can't be reused across corpora.

## Setup

```bash
pip install -e .       # installs deps and registers the `scr-bench` command
cp .env.example .env   # fill in ANTHROPIC_API_KEY (+ MCP_* for the mcp variant)
```

After that you can run any command two ways — `scr-bench --corpus nf-htan status`
or `python -m scr_bench.cli --corpus nf-htan status`. They're identical; use
whichever you prefer.

For the `zip` variant, extract the corpus's snapshots into its `fixtures/zip/`
first (paths are relative to the corpus directory):

```bash
cd corpora/nf-htan
mkdir -p fixtures/zip/ncihtan_htan2-data-model fixtures/zip/nf-osi_nf-metadata-dictionary
unzip "schemas-zip/ncihtan htan2-data-model main JSON_Schemas-v1.1.0.zip" \
  -d fixtures/zip/ncihtan_htan2-data-model
unzip "schemas-zip/nf-osi nf-metadata-dictionary main registered-json-schemas.zip" \
  -d fixtures/zip/nf-osi_nf-metadata-dictionary
cd ../..
```

The `zip` `dir` names in `corpus.yaml` must match the extracted folders above.

The `mcp` variant additionally needs an MCP server that exposes the schema graph;
set `MCP_SERVER_URL` and `MCP_TOKEN` in `.env`, and the corpus's CoreModels
project in `corpus.yaml` (`sources.mcp.project_id`). `MCP_TOKEN` is a **Bearer
token**: the connector sends it to the server as an `Authorization: Bearer
<token>` header. It is not passed in the prompt body.

## Usage

Every command takes `--corpus <name>` (a directory under `corpora/`):

```bash
scr-bench --corpus nf-htan check                 # validate env + config + samples
scr-bench --corpus nf-htan run                   # run the matrix (idempotent; skips completed cells)
scr-bench --corpus nf-htan run --variant mcp     # restrict to one variant / sample-type / model / rep
scr-bench --corpus nf-htan status                # show matrix coverage
scr-bench --corpus nf-htan report                # emit results/runs.csv + plots
```

Runs are deterministic by `run_id` (`variant__sample__model__rep`) and persisted
atomically under the corpus's `results/`, so an interrupted sweep resumes where
it left off.

## Configuration

- `config.yaml` — **global** matrix defaults (models, variants, sample types,
  reps, `max_tokens`, `temperature`, `grader_model`) shared across corpora.
- `corpora/<name>/corpus.yaml` — **per-corpus** settings: schema `sources`
  (url / zip / mcp), `universe_description` (used by the grader), and optional
  overrides of any matrix default.
- `.env` — secrets only: `ANTHROPIC_API_KEY`, and `MCP_SERVER_URL` / `MCP_TOKEN`
  for the mcp variant (never committed).
- `corpora/<name>/samples/*.json` — the input samples and their `expected`
  grading blocks.

## Adding a new corpus

1. `mkdir -p corpora/<name>/{samples,schemas-zip}`.
2. Write `corpora/<name>/corpus.yaml` — set `universe_description` and
   `sources` (url repos, zip `dir`/`label` pairs, and `mcp.project_id`). Use
   `corpora/nf-htan/corpus.yaml` as the template.
3. Add `samples/*.json` for the new schemas (exact / ambiguous / foreign /
   chimeric), each with an `expected` grading block.
4. Drop pinned `schemas-zip/*.zip` in and extract to `fixtures/zip/` (zip
   variant); load the schemas into a CoreModels project (mcp variant).
5. `scr-bench --corpus <name> check`, then `run`, `status`, `report`.

No code changes are needed — corpus identity is fully data-driven.

## Layout

```
config.yaml         # global matrix defaults
corpora/<name>/     # one self-contained corpus (see "Corpora" above)
src/scr_bench/
  cli.py            # command-line entry point (--corpus selects the corpus)
  config.py         # .env + config.yaml + corpus.yaml loading
  runner.py         # matrix iteration + per-cell execution
  grader.py         # LLM-as-judge structured grading
  metrics.py        # aggregate metrics from runs.jsonl
  plots.py          # matplotlib charts
  persistence.py    # deterministic run IDs, atomic writes, resume
  variants/         # mcp / url / zip retrieval surfaces
  tools/            # sandboxed bash executor for url/zip
```

## Metrics

- **tokens-to-correct** — mean `total_tokens` on correct runs per
  `(model, variant, sample_type)`.
- **correctness by model** — correct-answer rate per `(model, variant)` across
  sample types.

Token counts are summed across **every** turn of a run (including the MCP
server-side loop and the client-side tool loops). Cached input tokens are
reported separately for transparency.

## License

This project is licensed under the **Apache License 2.0** — see [LICENSE](LICENSE).
Apache-2.0 includes an express patent grant and patent-retaliation clause; it is
the standard license across the Schematica open-source ecosystem.

Copyright 2026 Hexagon Holdings LLC.

### Third-party data

The schema snapshots under `corpora/*/schemas-zip/` are redistributed from their
upstream projects for benchmark reproducibility and are **not** covered by the
Apache-2.0 license above. See [NOTICE](NOTICE) for details.

- **NF-OSI** ([`nf-osi/nf-metadata-dictionary`](https://github.com/nf-osi/nf-metadata-dictionary)) — collection under CC0.
- **HTAN2** ([`ncihtan/htan2-data-model`](https://github.com/ncihtan/htan2-data-model)) — MIT License, © 2024 Adam Taylor.
