# FHIR Corpus — Run Summary (smoke test)

> **Provenance.** Smoke test, **July 2026**. Corpus: HL7 **FHIR R6 (6.0)**
> JSON Schema — one monolithic draft-06 document (~4.25 MB, 887 resource/type
> definitions) fetched from content.coremodels.io. The `mcp` variant queries a
> CoreModels MCP server exposing the same schema graph. Matrix trimmed to prove
> the harness runs on a new corpus: **haiku-4-5, `exact` sample only, all three
> variants.** Directional, not a statistical result.

> **Cost figures updated Sept 2026.** Token numbers here are now `billed_tokens`
> (input + output + cache read + cache write) rather than the old cache-blind
> `total_tokens`. See [nf-htan/SUMMARY.md](../nf-htan/SUMMARY.md) for the full
> rationale. The correction matters most on this corpus — see Findings.

## Purpose

Validate that the corpus-parameterized harness runs end to end on a corpus other
than nf-htan, with **no code changes** — only a new `corpus.yaml`, one sample,
and the schema file.

## Sample

One `exact` sample: a LOINC-coded laboratory **Observation** (`status`, `code`,
`subject`, `effectiveDateTime`, `valueQuantity`), `resourceType` omitted so the
model must identify the resource from field shape. Expected: commit to
`Observation`.

## Results

| Variant | Result | Schema | Billed tokens | Cost | Turns | Tool calls | Wall |
|---|---|---|---:|---:|---:|---:|---:|
| **mcp** | ✅ correct **5/5** | `Observation` (commit) | 284,414 (mean) | $0.0658 | 2 | 17 | ~74 s |
| **zip** | ✅ correct | `Observation` (commit) | **7,607** | **$0.0099** | 5 | 4 | ~11 s |
| **url** | ❌ error | — | — | — | — | — | — |

`url` failed on context overflow: **205,251 > 200,000** tokens.

Both graded surfaces cited the same disambiguators (status + LOINC code + subject +
valueQuantity + effectiveDateTime).

> **On the mcp `n=5`.** The manifest carries five rows under a single `run_id`
> (`mcp__e-exact-fhir-observation__haiku-4-5__rep1`) — five `--force` re-runs of
> **one** cell, not five independent reps, and they share one raw artifact. They are
> retained deliberately as repeat observations of the same cell. Read the spread
> accordingly: individual runs billed 113,300 / 172,067 / 184,829 / 316,510 /
> 635,365 (stdev 209,771).

## Findings

- **Every completed run was correct.** mcp committed to `Observation` on all five
  repeats and zip on its one — 6/6 correct answers across the two surfaces that
  could complete, with no hallucination and no over-narrowing. Answer stability
  under repetition is exactly what the benchmark wants from a retrieval surface.
- **The harness is corpus-agnostic.** A brand-new corpus ran through
  run → grade → persist → report → plots with zero code changes.
- **`url` overflowed — a real result, not a crash.** Given a single 4.25 MB
  schema and `web_fetch`, the model pulled the whole document into context and
  exceeded the 200K window. The harness recorded an error record and continued.
  This is the **context-bloat failure mode** the benchmark is designed to expose,
  in its extreme form (infeasible, not merely expensive).
- **On a single-file corpus, grep is the right tool — and that sharpens the thesis.**
  Under correct cost accounting zip is the clear winner here: **7,607 billed tokens
  ($0.0099)** against mcp's **284,414 ($0.0658)**. Even mcp's cheapest repeat
  (113,300) is 15× zip's total, so this is not an artifact of averaging the five
  runs — and the single run the earlier draft of this document quoted (7,232
  cache-blind) in fact billed 316,510, or 42× zip.

  *Previously this section reported "mcp and zip cost about the same (~7.2 K vs
  7.6 K)". That comparison used `total_tokens`, which excluded the cache traffic
  that carries essentially all of mcp's server-side work. The claim is withdrawn.*

  The useful reading is a **scoping result, and a positive one**: FHIR R6 is the
  corpus where a graph surface has the least to offer — one flat document, no
  cross-file traversal to amortize, and `grep` answers in four tool calls. SCR's
  advantage is specific to corpora whose structure has to be *navigated*; it is not
  a general claim that graph lookup beats file reading everywhere. openEHR (many
  small files, real cross-type references) is where that advantage should appear,
  and [it does](../openehr/SUMMARY.md) — the graph comes in at half the cost of
  naive URL navigation there. Knowing precisely where the technique does *not* pay
  is what makes the claim credible where it does.
- **mcp is also the slowest surface here** (~74 s vs ~11 s), being 17 sequential
  graph round-trips against a corpus that needs one grep.

## MCP concurrency: root cause found and mitigated

Earlier mcp runs stalled ~300 s: a batch of **parallel** tool calls would hang,
release together at the connector's 300 s timeout, and drop exactly one call
(`is_error=True`). Server-side diagnostics resolved it. The CoreModels MCP server
**received and processed every call fast** (≤23 s, mostly ~200 ms), but two
concurrent requests arrived carrying the **same JSON-RPC id**. Since the JSON-RPC
id is assigned by the **client** (Anthropic's MCP connector), this is a
**connector bug: it assigns colliding ids to parallel tool calls**, so one
response can't be matched and that call times out. It only triggers under
concurrency; sequential calls always succeed (which is why interactive/manual
tests never saw it).

**Mitigation** (in `src/scr_bench/variants/mcp.py`): set
`tool_choice: {disable_parallel_tool_use: true}` so the model issues one tool call
per turn. With no parallel calls there are no id collisions — the final run above
made **17 sequential calls with zero stalls** and finished in ~74 s (vs ~370–940 s
when parallel calls stalled). Root cause is on Anthropic's side; this is a clean
client-side workaround. *(Aside: the server's `run_code` tool returns a fast error
when the model tries it — see the `graph_` code-mode note in
[nf-htan/SUMMARY.md](../nf-htan/SUMMARY.md); the model recovers via `search_nodes`.)*

## Caveats

- Small-n: one sample, one model, one cell per variant. Directional only. The mcp
  cell's five rows are repeats of that one cell, not independent reps.
- The `exact` sample does not exercise FHIR's cross-resource references, where a
  graph surface is expected to compound its advantage — untested here, and the most
  likely place for the cost picture on this corpus to change.
- The `url` cell can be made to complete (not necessarily succeed) by capping
  `web_fetch` content; see the repo notes on fixing the url variant for
  single-file corpora.
