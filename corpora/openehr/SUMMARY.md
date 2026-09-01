# openEHR Corpus — Run Summary (smoke test)

> **Provenance.** Smoke test, **July 2026**. Corpus: **openEHR RM (Reference
> Model) Release-1.1.0** JSON Schemas — per-class files published in the
> openEHR `specifications-ITS-JSON` GitHub repo (multi-file). The `mcp` variant
> queries a CoreModels MCP server exposing the same schema graph.
> Matrix: **haiku-4-5, all three variants** (`mcp` / `url` / `zip`). The original
> smoke was 1 rep on the `exact` sample; a **July 2026 update** added an
> `underdetermined` (A4 / refusal) sample at 3 reps and re-ran `exact`-zip at 3 reps
> after a sandbox bug invalidated the first zip runs (see the sandbox note). Small-n,
> directional.

> **Cost figures updated Sept 2026.** Token numbers here are now `billed_tokens`
> (input + output + cache read + cache write) rather than the old cache-blind
> `total_tokens`. See [nf-htan/SUMMARY.md](../nf-htan/SUMMARY.md) for the rationale.
> The stale duplicate manifest row described in the sandbox note has also been
> removed, so `exact`-zip now aggregates the three valid reps and nothing else.

## Purpose

Second new-corpus validation of the corpus-parameterized harness (after FHIR),
this time on a **many-file** schema repo — and a check of the SCR token-efficiency
claim where the graph surface is expected to help most.

## Sample

One `exact` sample: an openEHR **`DV_QUANTITY`** data value —
`magnitude: 120.0`, `units: "mm[Hg]"`, `precision: 0`, `units_system`,
`units_display_name`. The `_type` discriminator is omitted so the model must
identify the type from field shape. Expected: commit to `DV_QUANTITY`.

## Results — `exact`

| Variant | Result | Schema | Billed tokens | Cost | Turns | Tool calls | Wall |
|---|---|---|---:|---:|---:|---:|---:|
| **mcp** | ✅ correct (n=1) | `DV_QUANTITY` (commit) | 70,253 | $0.0300 | 1 | 7 | ~34 s |
| **zip** | ✅ correct (3/3) | `DV_QUANTITY` (commit) | **16,515** | **$0.0227** | 4–8 | 3–7 | 11–28 s |
| **url** | ✅ correct (n=1) | `DV_QUANTITY` (commit) | 142,779 | $0.0758 | 1 | 7 | ~17 s |

zip reps individually: 21,450 / 7,391 / 20,703 billed (mean 16,515).

All three surfaces cited the same disambiguators (magnitude + units + precision +
units_system + units_display_name).

> **Sandbox note (July 2026).** The zip variant runs the model's `run_bash` against a
> **local** bash sandbox. When the harness is launched from a shell without Git Bash
> on PATH, `bash` fails to resolve and *every* command errors — the model then
> silently falls back to answering from parametric knowledge, yet the harness still
> records an `ok` result. The original `exact`-zip smoke (`5,207` tokens, "grepped
> 103 files") was one such run: it never read a file and guessed `DV_QUANTITY`
> correctly by luck. Fixed by putting Git Bash on PATH and re-executing with real
> file access. **Sept 2026:** that invalid run's manifest row had survived the
> re-run as a duplicate `run_id` and was still being averaged in; it has now been
> removed. Hardening the sandbox to raise instead of degrade silently is queued.

## Findings

- **All three surfaces correct.** mcp, url, and zip each committed to
  `DV_QUANTITY` with the right reasoning; no hallucination, no over-narrowing.
  This is the corpus where every retrieval strategy works — the differences are
  purely about cost.
- **The graph beats naive URL navigation ~2×.** mcp used **70,253** billed tokens
  ($0.0300) against url's **142,779** ($0.0758) — a 2.0× token and 2.5× cost
  advantage for the graph surface over fetching from GitHub. *(An earlier draft put
  this at ~5×, comparing cache-blind `total_tokens`. The direction holds; the
  multiple is smaller.)*
- **Well-organized local files are cheaper still.** zip came in at **16,515** billed
  ($0.0227), the cheapest of the three. When the corpus is already on disk and
  cleanly split one-class-per-file, reading it directly beats both remote surfaces.
  Notably the corrected accounting *improves* zip's standing against url — the
  earlier "only ~1.4× under url" reading compared zip's uncached total against url's
  uncached total and missed the cache traffic url accumulates; the real gap is 8.6×.
- **A clean statement of where the graph pays.** Ranking on this corpus is
  **zip < mcp < url**. The graph's value here is that it beats the *remote*
  alternative decisively while needing no local corpus checkout — the realistic
  comparison for an integration that cannot ship 103 schema files to the client.
  Against a pre-extracted local corpus, direct file reading is hard to beat on a
  small, tidy candidate set. Contrast [FHIR](../fhir/SUMMARY.md) (one 4 MB file,
  where grep dominates) and [nf-htan](../nf-htan/SUMMARY.md) (93 flat files, where
  the picture turns on model tier): corpus shape, not surface alone, sets the
  ranking.
- **url navigated fine — no context overflow.** Because the schemas are many
  small files, the model fetched only the relevant one (`DV_QUANTITY.json`) and
  stayed well under the context window — the opposite of the FHIR `url` cell,
  which overflowed on the monolithic 4 MB document. Same variant, corpus shape
  decides the outcome.
- **mcp ran clean** (7 sequential calls, ~34 s, no ~300 s stalls) with
  `disable_parallel_tool_use` — the connector id-collision mitigation holds on the
  openEHR project too.

## A4 / refusal (under-determined input) — July 2026

> An `underdetermined` sample probes refusal: an input that matches **several**
> in-scope types with **no disambiguating field**, where the correct behavior is to
> **refuse or narrow**, not commit. Committing to a single type is a false-confidence
> failure. haiku-4-5, 3 reps/variant, field order shuffled per rep.

**Sample (f) underdetermined** — an ENTRY payload carrying only the shared
CARE_ENTRY attributes `{name, language, encoding, subject, data}` with **no root
`_type`**. Those five fields are present in **three** ENTRY subtypes —
`OBSERVATION`, `EVALUATION`, `ADMIN_ENTRY` — each a separate per-class file. The
fields that would disambiguate live behind references (`state`, present only on
OBSERVATION; and the runtime type of `data` — HISTORY vs ITEM_STRUCTURE), neither
resolvable from the flat payload. Correct = narrow to those three / decline.

| variant | reps | outcome | billed (mean) |
|---|---|---|---:|
| **mcp** | 3 | **3 false commit** (OBSERVATION ×2, EVALUATION ×1) — had every candidate but committed anyway; one rep explicitly listed EVALUATION + ADMIN_ENTRY as also-matching, then still committed | 358,191 |
| **url** | 3 | 1 correct decline, **2 false commit** — correct when it fetched the sibling schemas, wrong when it satisficed on `OBSERVATION.json` and asserted uniqueness | 338,598 |
| **zip** | 3 | **3 correct narrow** — read all candidate files, enumerated exactly `{OBSERVATION, EVALUATION, ADMIN_ENTRY}`, and independently flagged that `data`'s type is the reference-behind disambiguator | 189,405 |

**Read:** with a **small, well-organized candidate set** (three ENTRY files in one
folder), the surface that forces exhaustive reading (**zip**) refuses correctly —
3/3, and on the smallest token volume of the three (189,405 billed vs mcp's
358,191 and url's 338,598). In *dollars* the ranking flips — zip is the most
expensive at $0.2011 against mcp's $0.1016 and url's $0.1326 — because zip's
traffic is all uncached input billed at the full rate, while the graph and fetch
surfaces move more tokens but read most of them from cache at a tenth of it. A
useful reminder that on this benchmark "cheaper" has to name its unit.

The surface with an easy ranked lookup
(**mcp** graph) satisfices and over-commits, even though the graph *reaches* every
candidate. It is not a reference-reachability failure; it is that easy retrieval
removes the friction that would otherwise push the model to enumerate before
committing.

This is the same mechanism [nf-htan](../nf-htan/SUMMARY.md) surfaces at scale:
structured retrieval accelerates whatever disposition the model already has, so it
helps a well-calibrated model narrow and helps an over-committer commit. The
constructive takeaway is concrete and actionable — **a graph surface used for
schema identification should be paired with an explicit enumerate-then-commit step**
(as `schema-identification.md` prescribes) rather than relying on retrieval quality
alone. Contrast nf-htan's under-determined sample, where the true candidate set is
large (29 of 93) and in a flat directory: there even exhaustive reading over-commits
or exhausts its turn budget. Refusal behavior is dominated by model calibration and
candidate-set size/navigability, not a simple surface ranking.

## Caveats

- Small-n: one model; `exact` is n=1 for mcp and url, n=3 for zip; `underdetermined`
  is n=3 throughout. Directional only.
- The `exact` sample does not exercise openEHR's rich cross-type references
  (COMPOSITION → ENTRY → ELEMENT → DV_*), where the graph surface is expected to
  compound its advantage further — untested here.
- The zip variant assumes a pre-extracted local corpus; an integration that must
  ship or unzip the schemas first would pay extra up front that these numbers do
  not include.
