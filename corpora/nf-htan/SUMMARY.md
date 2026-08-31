# SCR Benchmark — Results Summary

> Results summary for the structured-context-retrieval benchmark: measurements, plots, and methodology notes. Updated as the test matrix fills in.

> **Provenance — read before quoting any number.** This corpus was filled in three waves:
>
> - **April 2026** — opus-4-7 and haiku-4-5 on samples (a)–(d), against **HTAN2 v1.1.0** and the then-current MCP tool surface (`core_models_project_content_summary`, `core_models_fetch_node`, …).
> - **July 2026** — haiku-4-5 on sample (e) `underdetermined`, against HTAN2 v1.2.0, field order shuffled per rep.
> - **Sept 2026** — sonnet-4-6 across all five samples, plus opus-4-7 on (e). Against HTAN2 v1.2.0 and a **re-synchronized MCP graph with a different tool surface** (`get_project_summary`, `search_nodes`, `list_projects`, `run_code`).
>
> The schema-version drift (v1.1.0 → v1.2.0) is cosmetic and does not confound tier comparisons. **The MCP tool-surface change does**: the April MCP cells and the Sept MCP cells did not query the same tool set. Model-tier comparisons *within* the Sept wave (opus vs sonnet on `underdetermined`) are clean; MCP comparisons *across* waves are not.

## Thesis

**Structured Context Retrieval (SCR)** — traversing a typed semantic graph at runtime via MCP — should produce materially better behavior than unstructured retrieval (raw GitHub URLs, local ZIPped schema files) on three properties: **token efficiency, determinism, and accuracy under under-claim discipline**.

This document reports how the data supports or refutes that thesis. As of the Sept 2026 wave the honest verdict is: **determinism holds and is stronger than we thought, accuracy is non-monotonic in model tier, and token efficiency does not survive correct cost accounting.**

## Current scope

| Dimension | Measured | Full matrix target | Status |
|---|---|---|---|
| Sample types | exact, ambiguous, foreign, chimeric, underdetermined | same 5 | **5/5** |
| Variants | mcp, url, zip | mcp, url, zip | 3/3 |
| Models | opus-4-7, sonnet-4-6, haiku-4-5 | opus-4-7, sonnet-4-6, haiku-4-5 | **3/3** |
| Reps per cell | 3 | 3 | OK |
| **Total runs** | **135** | **135** | **100%** |

Every one of the 135 rows is `status=graded`; there are no error rows in the manifest. Grader is `claude-opus-4-7` at `temperature=0` for every grading call across every variant and model. Self-grading bias is intentionally accepted because it is *constant* across the comparison and therefore cancels when comparing variants or models — disclosed as a reproducibility note.

## Retrieval scenarios (variants under test)

- **`mcp`** — CoreModels MCP server. The model traverses the typed schema graph at runtime. The Anthropic API handles the MCP tool-use loop server-side, so one client API call covers an arbitrary-length traversal. *(Tool surface differs between the April and Sept waves — see provenance.)*
- **`url`** — GitHub URLs (`ncihtan/htan2-data-model`, `nf-osi/nf-metadata-dictionary`) via `web_search` + `web_fetch` (server-side) plus a sandboxed `run_bash` (client-side). Mirrors a real coding-agent toolbox.
- **`zip`** — local extracted schemas in `fixtures/zip/`. The model has only a `run_bash` tool, sandboxed to read-only operations on the schema directory with network blocked.

All three variants share the same model, same `max_tokens`, same system prompt. Only the tool surface and the prompt body differ.

## Sample types tested

| Sample | Payload | Correct behavior | Predicted failure mode |
|---|---|---|---|
| **(a) exact** | All 5 fields present in NF-OSI `BiospecimenTemplate` | Commit to `BiospecimenTemplate`, cite path/ID | Confabulate, pick a wrong schema, or fail to commit |
| **(b) ambiguous** | Shared identifiers in 27+ templates, plus `bodySite` unique to BiospecimenTemplate | Use `bodySite` to commit | Pattern-match on shared identifiers, pick a wrong assay template |
| **(c) foreign** | Financial-transaction fields, outside the universe | Decline; declare no match | Invent or force-fit a schema |
| **(d) chimeric** | NF camelCase mixed with HTAN `SCREAMING_SNAKE` in one payload | Flag inconsistency; name both candidates | Silently commit to one and drop conflicting fields |
| **(e) underdetermined** | `{individualID, specimenID, aliquotID}` only — co-occur in **29 of 93** templates, no disambiguator | **Decline or narrow** | Commit anyway (false confidence) |

The grader is told the per-sample expected behavior and (for sample b) the disambiguator via `expected.grading_note`.

## ⚠️ Cost metric changed (Sept 2026) — earlier figures were wrong

Every token figure below is **`billed_tokens`** = `input + output + cache_read + cache_creation`.

Previous versions of this document reported `total_tokens`, which the run record defines as **input + output only**. That excluded prompt-cache traffic. The MCP variant runs its tool loop server-side and bills nearly all of that traffic as cache reads/writes, so the old metric counted roughly **3% of what an MCP run actually consumed** — one MCP run showed 4,500 `total_tokens` against 148,120 billed. The old figures systematically flattered MCP.

`metrics.py` now exposes three measures, all derived from fields already present in every record, so they apply retroactively to runs collected before the metric existed:

- **`billed_tokens`** — every billed token. Price-independent. **Default.**
- **`cost_usd`** — price-weighted at list rates, with cache writes at 1.25× and cache reads at 0.1× the base input rate. This is what the "cheaper" claim actually rests on.
- **`in_out`** — reproduces the old cache-blind figure, retained so prior numbers remain checkable.

**Tokens and dollars disagree, and the disagreement is the point.** MCP moves far more tokens than the old metric showed, but the bulk of them are cache *reads*, billed at a tenth of the input rate. MCP is token-heavy and dollar-light. Quote whichever suits the claim — just never quote `in_out` again.

## Headline result — cost-to-correct (Test 1)

Mean over **correct** runs only. Plots: [exact](results/plots/tokens_to_correct__exact.png), [ambiguous](results/plots/tokens_to_correct__ambiguous.png), [foreign](results/plots/tokens_to_correct__foreign.png), [chimeric](results/plots/tokens_to_correct__chimeric.png), [underdetermined](results/plots/tokens_to_correct__underdetermined.png).

### Opus 4.7 — billed tokens (n=3 per cell)

| Sample | mcp | zip | url | cheapest |
|---|---:|---:|---:|---|
| exact | 65,766 | **32,131** | 158,966 | zip |
| ambiguous | 68,416 | **28,309** | 88,334 | zip |
| foreign | 32,271 | **16,954** | 31,228 | zip |
| chimeric | 102,490 | **40,937** | 57,339 | zip |
| underdetermined | 146,857 | **19,082** | 81,754 (n=2) | zip |

### Opus 4.7 — cost USD

| Sample | mcp | zip | url |
|---|---:|---:|---:|
| exact | $0.2834 | **$0.1879** | $0.4393 |
| ambiguous | $0.1846 | **$0.1466** | $0.3180 |
| foreign | $0.1604 | **$0.1133** | $0.1550 |
| chimeric | $0.3360 | **$0.1998** | $0.2429 |
| underdetermined | $0.3573 | **$0.1302** | $0.3618 (n=2) |

**On Opus 4.7 the old headline inverts.** The April document claimed MCP was 5–16× cheaper than ZIP. Counted honestly, **ZIP is cheaper than MCP on every sample type, on both tokens and dollars** — by 1.3–7.7× in tokens and 1.3–2.7× in dollars. The old 5–16× figure was an artifact of not counting cache traffic.

### Sonnet 4.6 and Haiku 4.5 — cost USD (correct runs only)

| Sample | sonnet mcp | sonnet zip | sonnet url | haiku mcp | haiku zip | haiku url |
|---|---:|---:|---:|---:|---:|---:|
| exact | **$0.2229** | $0.3191 | $0.4254 | **$0.0512** | $0.1984 | $0.1183 (n=1) |
| ambiguous | **$0.1746** | $0.2857 | $0.5138 | **$0.0590** (n=2) | $0.1647 | — (0) |
| foreign | $0.1139 | **$0.0699** | $0.6658 | $0.0554 | $0.0625 | **$0.0528** |
| chimeric | **$0.1989** (n=1) | $0.6451 | $0.4435 | $0.0815 (n=2) | — (0) | $0.1512 (n=1) |
| underdetermined | — (0) | $0.2268 (n=2) | — (0) | $0.0646 (n=1) | — (0) | $0.1439 |

**Read:**

- **The cost story is tier-dependent, and it reverses.** MCP is the cheapest surface on haiku and mostly on sonnet, and the *most expensive* on opus. MCP's spend is dominated by a large, nearly fixed volume of cached graph context; that fixed cost is cheap at haiku's input rate and expensive at opus's. The cheaper the model, the better MCP looks.
- **Empty cells carry more weight than the numbers beside them.** `sonnet url underdetermined` has no cost entry because it was **0/3 correct**. Cost-to-correct is undefined where nothing is correct.

## Correctness (Test 3)

Plot: [results/plots/correctness_by_model.png](results/plots/correctness_by_model.png).

### Per-cell correctness (out of 3 reps)

| Sample | opus mcp | opus zip | opus url | sonnet mcp | sonnet zip | sonnet url | haiku mcp | haiku zip | haiku url |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| exact | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **1/3** |
| ambiguous | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | **0/3** |
| foreign | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| chimeric | 3/3 | 3/3 | 3/3 | **1/3** | 3/3 | 3/3 | 2/3 | **0/3** | **1/3** |
| underdetermined | 3/3 | 3/3 | 2/3 | **0/3** | 2/3 | **0/3** | **1/3** | **0/3** | 3/3 |
| **total** | **15/15** | **15/15** | **14/15** | **10/15** | **14/15** | **12/15** | **11/15** | **9/15** | **8/15** |

### MCP's effect on accuracy is non-monotonic in model tier

Rank of MCP among the three surfaces, by total correctness:

| Model | mcp | zip | url | MCP rank |
|---|---:|---:|---:|---|
| opus-4-7 | 15/15 | 15/15 | 14/15 | best (tied) |
| sonnet-4-6 | **10/15** | 14/15 | 12/15 | **worst** |
| haiku-4-5 | **11/15** | 9/15 | 8/15 | **best** |

This is the most important finding in the corpus, and it was invisible before the middle tier existed. The April write-up projected a smooth story — MCP helps more as the model gets weaker. The data does not do that. MCP is the best surface for haiku, the *worst* for sonnet, and a tie at opus.

### Hallucinations — 18 across 135 runs

| | mcp | zip | url | total |
|---|---:|---:|---:|---:|
| opus-4-7 | 0 | 0 | 1 | 1 |
| sonnet-4-6 | **5** | 1 | 3 | 9 |
| haiku-4-5 | 4 | 2 | 2 | 8 |
| **total** | **9** | **3** | **6** | **18** |

**MCP produces half of all hallucinations in the corpus.** 14 of the 18 land on `underdetermined` or `chimeric` — the two samples where the correct answer is to refuse or to flag rather than commit. The dominant failure is a confident commit to `BiospecimenTemplate`, the most salient template in the graph.

### The refusal result — sample (e) `underdetermined`

`{individualID, specimenID, aliquotID}` co-occur in 29 of 93 templates with no disambiguator. Correct behavior is decline or narrow. Behavior across the 9 runs per model:

| Model | commits (wrong) | narrows/declines (right) |
|---|---:|---:|
| opus-4-7 | 1/9 | **8/9** |
| sonnet-4-6 | **7/9** | 2/9 |
| haiku-4-5 | 4/9 | 5/9 |

Sonnet committed on **every** MCP and URL rep (0/3 and 0/3); only ZIP pulled it back to 2/3. Its retrieval was not at fault — it found the right element nodes — it skipped the *enumeration* step: checking which other types also contain all three fields. That is textbook satisficing, the failure mode `schema-identification.md` names as the primary way this task goes wrong.

**Structured retrieval accelerates whatever disposition the model already has.** For a well-calibrated model it accelerates correct narrowing (opus: 3/3 on MCP). For an over-committer it accelerates a confident wrong answer (sonnet: 0/3 on MCP, 2/3 on ZIP). ZIP's filesystem scan incidentally exposes *how many* templates share the fields; the graph hands over one authoritative answer fast. **The claim "SCR improves refusal discipline" does not survive the middle tier as stated.**

### ⚠️ ZIP + Haiku + chimeric: abstention by exhaustion

All 3 ZIP-haiku-chimeric reps hit `MAX_TURNS=25` with `stop_reason="tool_use"` — haiku kept calling `run_bash` and never committed within the loop budget. Final text was empty; graded `correct=False, hallucinated=False`. Not a hallucination, but not a useful answer either. Likely recoverable by raising `MAX_TURNS` to 40+, but the failure is itself signal and is kept on the record rather than tuned around.

## Determinism (Test 2 — partial)

`predicted_schema` is the same string in **100% of correct runs**, per variant per sample: the answer does not drift. Only the *cost* of reaching it does.

Cost variance — `stdev / mean` of `billed_tokens` across reps, **Opus 4.7, correct runs**:

| Sample | mcp | zip | url |
|---|---:|---:|---:|
| exact | **1%** | 20% | 70% |
| ambiguous | **0%** | 30% | 43% |
| foreign | **0%** | 8% | 2% |
| chimeric | **2%** | 25% | 33% |
| underdetermined | 27% | 20% | 21% |

**This is where SCR wins cleanly, and the corrected metric strengthens the case.** Under the old cache-blind measure MCP looked *noisy* (43–89% variance on three of four samples). Counting billed tokens shows the opposite: MCP's cost is near-perfectly reproducible — 0–2% on four of five samples — because the graph traversal is path-equivalent every time and the cached context is identical. The old metric was measuring the tiny uncached residue and mistaking its jitter for real variance.

> Answer determinism is fully established (100% identical `predicted_schema`); the percentages above are cost variance. A dedicated determinism strip plot (Levenshtein/embedding spread of `final_text`) needs multiple `sample_id`s per `sample_type`.

## Per-sample observations (Opus 4.7, April wave)

> Counts in this section are Opus 4.7 across 9 runs per sample (3 variants × 3 reps). Sonnet/haiku failures are covered above.

### Sample (a) exact
- 9/9 correct, 0 hallucinations.
- MCP rep 1 paid the cache miss (`input_tokens=2392`); reps 2–3 were 8 *uncached* input tokens — yet the run still billed ~65K. That gap is exactly the accounting error the new metric fixes.
- URL hit two 429s on rep 2; the SDK auto-retried successfully.

### Sample (b) ambiguous
- 9/9 correct, 0 hallucinations. No variant committed to a `wrong_but_tempting` assay template.
- 8 of 9 grader notes explicitly cite `bodySite`; the outlier (zip rep 1) committed correctly but cited "presence of all four fields".
- **The predicted accuracy story did not materialize at this tier** — all three surfaces reached the right answer with the right reasoning. It does materialize lower down (haiku url: 0/3).

### Sample (c) foreign
- 9/9 correct, 0 hallucinations. Cheapest sample for every variant.

### Sample (d) chimeric
- 9/9 correctly flagged inconsistency, 0 hallucinations.
- All three variants identified the same disambiguator: case convention.
- MCP cost was the most consistent of any sample (2% variance).

## Methodology notes and caveats

### 1. The `graph_` code-mode name collision (Sept wave, MCP only)

The Anthropic MCP connector namespaces tools to the model as `<server_name>_<tool>`. With our `MCP_SERVER_NAME = "graph"`, the model's tool list reads `graph_search_nodes`, `graph_get_project_summary`, …. But CoreModels' `run_code` sandbox registers those same tools under **bare** names (`tools.search_nodes`). The two layers disagree by construction, and models paste the outer name into the inner sandbox.

Measured across the corpus: **sonnet lost 26 of 34 `run_code` calls (76%)** to `Tool 'graph_X' is not available in code mode`; opus lost 1 of 6; haiku 1 of 1.

A controlled test (3 reps per condition) shows the prefix transfers only when it reads as a plausible namespace:

| server name | written inside `run_code` | rejected |
|---|---|---|
| `graph` | `graph_search_nodes` (3/3) | 3/3 |
| `zzqq` | `search_nodes` (3/3) | 0/3 |

So it is not mechanical namespacing — `graph` looks like a real module, `zzqq` looks like noise and gets dropped. **This inflated MCP token cost in the Sept wave but did not cause the accuracy failures**: the sonnet underdetermined runs ended `end_turn` at `turns=1` with budget to spare, and sonnet failed the same sample 0/3 on URL, where `run_code` does not exist. Renaming the server would fix it but changes the tool names in the prompt, so it requires a disclosed re-baseline rather than a quiet patch.

### 2. The ZIP variant assumes pre-extracted fixtures (Option A)

The headline ZIP number measures *retrieval* cost — once schemas are on disk, how expensive is it to find the right one? Alternatives considered: **Option B**, model unzips at runtime (adds 1–3 extract-and-list calls; more representative of "drop a zip into a chat"); **Option C**, inline every schema in the prompt (implemented behind `--include-raw`, not in the charts).

### 3. Caching dynamics affect every variant

URL and ZIP cache only the system prompt; multi-turn tool-result content is uncached. MCP caches the whole server-side loop. A real at-scale deployment of a non-MCP variant could close some of the gap with breakpoint-on-last-message caching — flagged so the MCP position is not overstated in either direction.

### 4. Model resolution audit trail

Every record includes `model_resolved` (the snapshot the alias resolved to). All runs resolved cleanly. Pin to dated snapshots before any further wave.

### 5. The manifest does not deduplicate

`load_runs` reads every JSONL line with no dedup by `run_id`, and the writer only appends. Re-running a cell with `--force` leaves **two** rows for the same `run_id` and both are counted. To re-baseline, archive the whole `results/` directory to a versioned sibling and start a fresh manifest — do not `--force` into the existing one.

## Reproducibility

- Pin model versions to dated snapshots in `config.yaml`. Aliases drift; dated IDs do not.
- Capture `response.model` per run into `model_resolved` so silent alias updates are visible.
- For the URL variant, snapshot the GitHub commit SHA via `git ls-remote` per run (deferred).
- No seed parameter exists for Claude; determinism comes from the absence of sampling parameters on Opus 4.7. The 3-rep design captures residual variance.
- Keep `results/raw/` and `results/runs.jsonl` under version control — grading rules will evolve and re-grading against existing artifacts is expected.
- Field-order shuffling is per-corpus and per-wave: samples (a)–(d) ran with `shuffle_field_order: false`, sample (e) with `true`. The flag must not be flipped mid-pass.

## What's still missing

- **An MCP re-baseline on a single tool surface.** The April and Sept MCP cells are not comparable. Until all three tiers are re-run against one surface, every cross-wave MCP claim carries an asterisk. Highest-value next experiment.
- **Why sonnet over-commits.** The middle tier is worse than both its neighbours at refusal. Whether that is a sonnet-4-6 calibration quirk or a general mid-tier effect needs a second mid-tier model to separate.
- Two still-missing charts: `determinism_strip.png` and `halluc_vs_abstain.png` — the strip plot needs multiple `sample_id`s per `sample_type`.
- Standalone re-grading command (`scr-bench grade --input results/raw/`) — sensitivity check against a different grader model.
- GitHub commit-SHA snapshot per URL run — `git ls-remote` at run start, logged into the record.
