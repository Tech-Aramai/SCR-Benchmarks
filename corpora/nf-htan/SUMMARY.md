# SCR Benchmark — Results Summary

> Results summary for the structured-context-retrieval benchmark: measurements, plots, and methodology notes. Updated as the test matrix fills in.

> **Provenance.** All results in this document were collected in **April 2026** against the then-current CoreModels graph and the schema set of that date — specifically **HTAN2 v1.1.0** plus the NF-OSI dictionary as it stood then. The corpus has **since moved to HTAN2 v1.2.0** (and the NF-OSI dictionary has grown), and the MCP graph has been re-synchronized, so these figures are a **point-in-time snapshot on a previous schema version**, not a measurement of the current corpus. The thesis-level findings do not depend on the specific schema version or tool surface.

## Thesis

**Structured Context Retrieval (SCR)** — traversing a typed semantic graph at runtime via MCP — should produce materially better behavior than unstructured retrieval (raw GitHub URLs, local ZIPped schema files) on three properties: **token efficiency, determinism, and accuracy under under-claim discipline**.

This document reports how the data supports or refutes that thesis. Token efficiency (Test 1) and accuracy / abstention (Test 3) are measured in full; determinism (Test 2) holds at the answer level (100% identical `predicted_schema`), with cost-variance reported alongside pending a dedicated strip plot.

## Current scope

| Dimension | Measured so far | Full matrix target | Status |
|---|---|---|---|
| Sample types | exact, ambiguous, foreign, chimeric | exact, ambiguous, foreign, chimeric | **4/4** |
| Variants | mcp, url, zip | mcp, url, zip | 3/3 |
| Models | claude-opus-4-7, claude-haiku-4-5 | opus-4-7, sonnet-4-6, haiku-4-5 | 2/3 |
| Reps per cell | 3 | 3 | OK |
| **Total runs** | **72** | **108** | 67% |

Grader is `claude-opus-4-7` at `temperature=0` for every grading call across every variant and every model under test. Self-grading bias is intentionally accepted because it is *constant* across the comparison and therefore cancels out when comparing variants or models — disclosed as a reproducibility note.

## Retrieval scenarios (variants under test)

- **`mcp`** — CoreModels MCP server. The model traverses the typed schema graph at runtime via tools like `core_models_project_content_summary` and `core_models_fetch_nodes`. The Anthropic API handles the MCP tool-use loop server-side, so one client API call covers an arbitrary-length traversal. *(Tool surface as of April 2026; the singular node-fetch tool has since been removed from the MCP — see the provenance note above.)*
- **`url`** — GitHub URLs (`ncihtan/htan2-data-model`, `nf-osi/nf-metadata-dictionary`) via `web_search` + `web_fetch` (server-side) plus a sandboxed `run_bash` (client-side). Mirrors a real coding-agent toolbox — Claude Code / Cursor expose all three and let the model pick.
- **`zip`** — local extracted schemas in `fixtures/zip/`. The model has only a `run_bash` tool, sandboxed to read-only operations on the schema directory with network blocked.

All three variants share the same model, same `max_tokens`, same system prompt. Only the tool surface and the prompt body differ.

## Sample types tested

Each sample probes a different failure mode the benchmark was designed to catch:

| Sample | Payload | Correct behavior | Predicted failure mode |
|---|---|---|---|
| **(a) exact** | All 5 fields are present in NF-OSI `BiospecimenTemplate` (`individualID`, `parentSpecimenID`, `specimenID`, `aliquotID`, `tumorType`) | Commit to `BiospecimenTemplate`, cite path/ID | Confabulate, pick a wrong schema, or fail to commit |
| **(b) ambiguous** | Shared identifier fields (`individualID`, `specimenID`, `aliquotID`) appear in `BiospecimenTemplate` AND in 27+ NF assay templates, plus one disambiguating field (`bodySite`) unique to BiospecimenTemplate | Use `bodySite` to commit to `BiospecimenTemplate` | Pattern-match on shared identifiers and pick a wrong assay template (`GenomicsAssayTemplate` / `RNASeqTemplate` / `WGSTemplate`). This is where the "look up before you make up" claim is supposed to cash out. |
| **(c) foreign** | Financial-transaction fields (`transactionId`, `amount`, `currency`, `merchantId`, `settledAt`) — completely outside the NF-OSI / HTAN2 universe | Decline; declare no match | Invent a schema or force-fit financial fields onto an unrelated biomedical schema |
| **(d) chimeric** | NF-OSI camelCase (`individualID`, `tumorType`) mixed with HTAN `SCREAMING_SNAKE_CASE` IDs (`HTAN_BIOSPECIMEN_ID`, `HTAN_PARENT_ID`) in one payload | Flag inconsistency; name both candidate schemas (`BiospecimenTemplate` and `BiospecimenData`) | Silently commit to one schema and drop the conflicting fields |

The grader is told the per-sample expected behavior and (for sample b) the disambiguator field via the sample's `expected.grading_note`, so it can mark "committed correctly but didn't cite the disambiguator" differently from "committed correctly and cited the disambiguator".

## Headline result — tokens-to-correct (Test 1)

Mean `total_tokens` on **correct** runs, per `(model, variant, sample_type)`. Plots: [exact](results/plots/tokens_to_correct__exact.png), [ambiguous](results/plots/tokens_to_correct__ambiguous.png), [foreign](results/plots/tokens_to_correct__foreign.png), [chimeric](results/plots/tokens_to_correct__chimeric.png) — all grouped by model.

### Opus 4.7 (n=3 per cell)

| Sample | mcp | zip | url | mcp wins by |
|---|---:|---:|---:|---:|
| exact | 2,789 | 25,619 | 43,783 | 9–16× |
| ambiguous | 2,693 | 17,736 | 30,601 | 7–11× |
| foreign | 1,697 | 15,130 | 11,848 | 7–9× |
| chimeric | 5,250 | 25,075 | 25,062 | ~5× |

### Haiku 4.5 (n varies — only correct runs counted; see correctness section below)

| Sample | mcp (n) | zip (n) | url (n) | notes |
|---|---:|---:|---:|---|
| exact | 4,377 (3) | 59,865 (3) | 43,148 (1) | URL only correct on 1/3 reps |
| ambiguous | 4,477 (2) | 115,198 (3) | — (0) | URL **0/3 correct** — no token entry |
| foreign | 3,822 (3) | 53,894 (3) | 13,408 (3) | easiest sample for everyone |
| chimeric | 5,956 (2) | — (0) | 88,368 (1) | ZIP **0/3 correct** (hit `MAX_TURNS=25`) |

**Read:**
- Opus 4.7: MCP costs *5–16× fewer tokens* than URL/ZIP for the same correct answer on every sample type. Cost-only story; accuracy is parity.
- Haiku 4.5: MCP is *5–25× cheaper* than the variants that *can* produce a correct answer — but on hard samples URL and ZIP often *can't*. The story shifts from cost-only to cost+accuracy. See "Hallucination + abstention" below.
- ZIP-Haiku-ambiguous's stdev (58,411 tokens, with mean 115,198) means one rep alone burned ~166K tokens to land the answer — Haiku scans the whole filesystem when it's unsure.

**Honorable mention — Opus chimeric stdev=91 (MCP).** Three reps came in at 5,237 / 5,166 / 5,347 tokens — within a 200-token band. The cost determinism story is sharpest at this single point.

## Hallucination + abstention (Test 3 — full)

Plot: [results/plots/correctness_by_model.png](results/plots/correctness_by_model.png).

### Per-cell correctness (out of 3 reps each)

| Sample | mcp opus | mcp haiku | url opus | url haiku | zip opus | zip haiku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| exact | 3/3 | 3/3 | 3/3 | **1/3** | 3/3 | 3/3 |
| ambiguous | 3/3 | 2/3 | 3/3 | **0/3** | 3/3 | 3/3 |
| foreign | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| chimeric | 3/3 | 2/3 | 3/3 | **1/3** | 3/3 | **0/3** ⚠️ |
| **total** | **12/12** | **10/12** | **12/12** | **5/12** | **12/12** | **9/12** |

### Hallucinations

- **Opus 4.7**: **0 hallucinations** across all 36 runs. The predicted "URL/ZIP confabulate" failure mode did not materialize at this tier.
- **Haiku 4.5**: **3 hallucinations** — mcp(1) + url(2) + zip(0). All three land on the hardest sample, `chimeric`; on `exact`, `foreign`, and (once corrected — see below) `ambiguous`, Haiku did not confabulate.
  - **mcp — 1**: *chimeric* rep1 — correctly flagged inconsistency but named the **wrong second schema** (`nf-platebasedreporterassaytemplate`, a real NF template, in place of HTAN BiospecimenData).
  - **url — 2**, both on *chimeric* (rep1, rep3) — **committed to `HTAN BiospecimenData`** and ignored the NF/HTAN field mix instead of flagging it.
  - **Not hallucinations (under-claiming or graph noise):**
    - url `exact` / `ambiguous` (5 runs) — *appropriate abstentions* (`decline` / `narrow` / `flag_inconsistency`, `hallucinated=false`, no fabricated schema). Haiku got them wrong by **under-claiming**, not by making something up; the predicted "commit to a `wrong_but_tempting` assay template" mode did not appear even on Haiku.
    - mcp `ambiguous` rep1 — **over-narrowing, not fabrication.** It returned a candidate list (`BiospecimenTemplate` + a stray project node that was *temporarily* mis-titled `"biospecimen 21 23"`) instead of committing via `bodySite`. That node was **real graph noise** — a title since reverted in the project — not a model invention, so it is *not* counted as a hallucination. (A genuine SCR signal: stray/mislabeled graph nodes can pull a weak model into over-narrowing — a data-quality issue, not a model one.)
  - **zip — 0.** Its chimeric failures were turn-exhaustion, not hallucination (below).

### ⚠️ ZIP + Haiku + chimeric: abstention by exhaustion

All 3 ZIP-Haiku-chimeric reps hit `MAX_TURNS=25` with `stop_reason="tool_use"` — Haiku kept calling `run_bash` searching for the right schema and never committed within the loop budget. Final text was empty; the grader marked them all `correct=False, hallucinated=False`. This isn't a hallucination, but it isn't a useful answer either — *it's the model giving up by running out of turns*.

These could likely be recovered by raising `MAX_TURNS` to 40+, but the failure is itself a real signal: Haiku-class models can't navigate a flat directory of 86 schemas reliably enough to commit. We're keeping the failure on the record rather than tuning around it.

### What this means

The headline is a layered, tier-dependent story:

1. *On a frontier model (Opus 4.7), all three variants reach correct answers — but MCP does it at 5–16× lower token cost.*
2. *On a fast/cheap model (Haiku 4.5), MCP also rescues accuracy: URL drops to 5/12 (especially catastrophic on the disambiguator sample), ZIP drops to 9/12 (gets stuck on chimeric). MCP holds 10/12 with the structural shortcut.*
3. *Sonnet 4.6 is the missing middle tier — it would tell us whether the accuracy gap widens gradually or stepwise as model capability drops.*

## Determinism (Test 2 — partial)

`predicted_schema` is the same string in **100% of correct runs**, per variant per
sample: the answer does not drift run to run. Only the *cost* of reaching it does.

Cost variance — `stdev / mean` of `total_tokens` across the three reps, per variant
per sample:

| Variant | Stdev / mean (exact) | (ambiguous) | (foreign) | (chimeric) |
|---|---:|---:|---:|---:|
| mcp | 43% | 60% | 89% | **2%** |
| zip | 9% | 21% | 12% | 16% |
| url | 54% | 23% | 7% | 13% |

ZIP shows tight cost stability on most samples (disk scans of the same files produce nearly identical token counts). URL's variance is noisiest on `exact` because one rep spelunked through 4 candidate templates while the other two went straight to the answer. **MCP on chimeric is the standout** — three reps within a 200-token band of each other (5,237 / 5,166 / 5,347).

> Note: answer determinism is fully established (100% identical `predicted_schema`);
> the percentages above are cost variance. A dedicated determinism strip plot
> (Levenshtein/embedding spread of `final_text`) needs multiple `sample_id`s per
> `sample_type`.

## Per-sample observations

> Counts in this section are **Opus 4.7 (frontier tier)** — 9 runs per sample
> (3 variants × 3 reps), which is why they read 9/9 with 0 hallucinations. The
> Haiku-tier failures (including the 3 hallucinations) are covered in the
> Hallucination section above.

### Sample (a) exact — `BiospecimenTemplate` with all five identifying fields
- 9/9 correct. 0 hallucinations.
- MCP rep 1 paid the cache miss (`input_tokens=2392`); reps 2–3 were 8 input tokens because the system prompt cached and the work happened MCP-server-side.
- URL hit two 429s on rep 2; SDK auto-retried successfully (`max_retries=2` default) and the run completed without manual intervention.
- ZIP took 8–9 `run_bash` calls per run with very tight variance (stdev 2,340).

### Sample (b) ambiguous — same identifiers + `bodySite` as the disambiguator
- 9/9 correct. **0 hallucinations.** No variant committed to a `wrong_but_tempting` assay template.
- 8 of 9 grader notes explicitly cite `bodySite` as the disambiguator; the only outlier (zip rep 1) still committed correctly but cited "presence of all four fields" rather than naming `bodySite` specifically.
- **On Opus 4.7, the accuracy story did not materialize as predicted.** The benchmark design hypothesized URL/ZIP would pattern-match on shared identifiers and pick `GenomicsAssayTemplate` / `RNASeqTemplate` / `WGSTemplate`. On Opus 4.7, all three retrieval surfaces reached the right answer with the right reasoning. The cost-to-correct delta still holds; the accuracy delta does not — until the model tier drops (see Haiku results above).

### Sample (c) foreign — financial-transaction fields, expected to decline
- 9/9 correct. **0 hallucinations.** No variant invented a schema or force-fit financial fields onto a biomedical schema.
- This is the cheapest sample for every variant — once you've looked at the field names, "no match" is fast to confirm. MCP reps 2 and 3 did it in **792 and 850 total tokens**.
- Every grader note independently calls out the same failure mode that didn't happen ("financial fields have no analog in biomedical schemas"), confirming the model's reasoning was sound, not hand-wavy.

### Sample (d) chimeric — NF camelCase + HTAN SCREAMING_SNAKE in one payload
- **On Opus 4.7:** 9/9 correctly flagged inconsistency, **0 hallucinations** — no variant silently committed to one schema. *(On Haiku this was the weakest sample: url committed to `HTAN BiospecimenData` twice and mcp mis-cited the second schema once — see the Hallucination section.)*
- All three variants identified the same disambiguator: case convention. URL/ZIP reps cite "camelCase NF-OSI fields vs SCREAMING_SNAKE_CASE HTAN fields"; MCP reps cite the same split via node IDs.
- **MCP cost was the most consistent of any sample**: stdev=91 across three reps. The graph traversal is path-equivalent each time; URL/ZIP fan out differently per run.
- MCP wall time was longer (avg 263s vs ~50–60s for URL/ZIP) — the API's server-side MCP loop did extra work to confirm the two-registry split.

## Methodology notes and caveats

Points that aren't visible in the headline charts but matter for interpreting them.

### 1. The ZIP variant assumes pre-extracted fixtures (Option A)

The headline ZIP number measures *retrieval* cost — once the schemas are on disk, how expensive is it for the model to find the right one?

We considered two alternative simulations and chose A as the fairest baseline:

- **Option B — ship the zip, model unzips at runtime** (what claude.ai web does — a sandbox is provisioned and the agent invokes `unzip` itself). Adds 1–3 extract-and-list calls per run before the schema-identification loop begins. More representative of "drop a zip into a chat" integrations, but the extraction cost isn't part of the retrieval claim. Worth recording as a caveat: an integration that also unzips should expect some extra tokens up front.
- **Option C — inline every schema as text blocks in the user message**. No tools at all; the entire schema corpus rides in the prompt. Lower bound on cleverness, upper bound on context tokens. Implemented behind an `--include-raw` flag; not in the main charts.

### 2. Caching dynamics affect every variant

MCP reps 2 and 3 had `input_tokens=8` because the system prompt was cached on rep 1. URL and ZIP only cache the system prompt; multi-turn tool-result content is uncached. A real, at-scale deployment of any non-MCP variant could close some of the gap with breakpoint-on-last-message caching — worth flagging so the MCP win isn't oversold.

### 3. Model resolution audit trail

Every run record includes `model_resolved` (the snapshot the alias resolved to at request time). All current runs resolved their aliases to a single snapshot. Pin to dated snapshots in `config.yaml` before the full benchmark run; the audit trail catches alias drift mid-experiment.

## Reproducibility

- Pin model versions to dated snapshots in `config.yaml` before the full benchmark run. Aliases drift; dated IDs do not.
- Capture `response.model` per run into `model_resolved` so silent alias updates are visible.
- For the URL variant, snapshot the GitHub commit SHA via `git ls-remote` per run (deferred).
- No seed parameter exists for Claude; determinism comes from the absence of sampling parameters on Opus 4.7. The 3-rep design captures any residual variance.
- Keep `results/raw/` and `results/runs.jsonl` under version control or archived — grading rules will evolve and re-grading against existing artifacts is expected.

## What's still missing

- **Sonnet 4.6** — the missing middle tier between Opus 4.7 and Haiku 4.5; needed to see whether the accuracy gap widens gradually or stepwise as model capability drops. Highest-value next experiment.
- Two still-missing charts: `determinism_strip.png` and `halluc_vs_abstain.png` — the strip plot needs multiple `sample_id`s per `sample_type`.
- Standalone re-grading command (`scr-bench grade --input results/raw/`) — sensitivity check against a different grader model.
- GitHub commit-SHA snapshot per URL run (reproducibility) — `git ls-remote` at run start, logged into the record.
