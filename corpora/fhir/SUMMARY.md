# FHIR Corpus — Run Summary (smoke test)

> **Provenance.** Smoke test, **July 2026**. Corpus: HL7 **FHIR R6 (6.0)**
> JSON Schema — one monolithic draft-06 document (~4.25 MB, 887 resource/type
> definitions) fetched from content.coremodels.io. The `mcp` variant queries a
> CoreModels MCP server exposing the same schema graph. Matrix trimmed to prove
> the harness runs on a new corpus: **haiku-4-5, 1 rep, `exact` sample only, all
> three variants.** Not a statistical result (n=1).

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

| Variant | Result | Schema | Tokens | Turns | Tool calls | Wall | Note |
|---|---|---|---:|---:|---:|---:|---|
| **mcp** | ✅ correct | `Observation` (commit) | 7,232 | 2 | 17 | ~74 s | graph lookup; cited node id. Parallel tool use disabled to avoid a connector id-collision stall (below) |
| **zip** | ✅ correct | `Observation` (commit) | 7,607 | 5 | 4 | ~11 s | haiku grepped the 4 MB file rather than reading it whole |
| **url** | ❌ error | — | — | — | — | — | context overflow: **205,251 > 200,000** tokens |

Both graded surfaces cited the same disambiguators (status + LOINC code + subject +
valueQuantity + effectiveDateTime).

## Findings

- **The harness is corpus-agnostic.** A brand-new corpus ran through
  run → grade → persist → report → plots with zero code changes.
- **`url` overflowed — a real result, not a crash.** Given a single 4.25 MB
  schema and `web_fetch`, the model pulled the whole document into context and
  exceeded the 200K window. The harness recorded an error record and continued.
  This is the **context-bloat failure mode** the benchmark is designed to expose,
  in its extreme form (infeasible, not merely expensive).
- **Scoped surfaces won; naive fetch failed.** Both mcp (graph) and zip (grep)
  committed correctly and cheaply; the fetch-everything path could not complete.
- **mcp and zip cost about the same in tokens here** (~7.2 K vs 7.6 K), and mcp is
  slower on the clock (~74 s vs ~11 s, being 17 sequential graph round-trips). On
  this single-file corpus the token-efficiency edge mcp showed on nf-htan's
  many-file corpus (5–16×) does **not** appear — zip greps one file cheaply.

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
when the model tries it — unrelated to this issue; the model recovers via
`search_nodes`.)*

## Caveats

- n=1: one sample, one model, one rep. Directional only, not evidence.
- The `exact` sample does not exercise FHIR's cross-resource references, where a
  graph surface is expected to compound its advantage — untested here.
- The `url` cell can be made to complete (not necessarily succeed) by capping
  `web_fetch` content; see the repo notes on fixing the url variant for
  single-file corpora.
