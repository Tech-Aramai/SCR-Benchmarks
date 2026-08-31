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

## Purpose

Second new-corpus validation of the corpus-parameterized harness (after FHIR),
this time on a **many-file** schema repo — and a check of the SCR token-efficiency
claim where the graph surface is expected to help most.

## Sample

One `exact` sample: an openEHR **`DV_QUANTITY`** data value —
`magnitude: 120.0`, `units: "mm[Hg]"`, `precision: 0`, `units_system`,
`units_display_name`. The `_type` discriminator is omitted so the model must
identify the type from field shape. Expected: commit to `DV_QUANTITY`.

## Results

| Variant | Result | Schema | Tokens | Turns | Tool calls | Wall | Note |
|---|---|---|---:|---:|---:|---:|---|
| **mcp** | ✅ correct (n=1) | `DV_QUANTITY` (commit) | **4,521** | 1 | 7 | ~34 s | graph lookup; cited node id. Clean, no stalls |
| **zip** | ✅ correct (3/3) | `DV_QUANTITY` (commit) | **~16,500** | 4–8 | 3–7 | 11–28 s | read the local per-class files. **Re-run July, n=3** (21.5K / 7.4K / 20.7K) — the original `5,207` was a broken-sandbox run that never read disk; see note |
| **url** | ✅ correct (n=1) | `DV_QUANTITY` (commit) | **22,640** | 1 | 7 | ~17 s | navigated the GitHub folder to `Data_types/DV_QUANTITY.json` |

All three surfaces cited the same disambiguators (magnitude + units + precision +
units_system + units_display_name).

> **Sandbox note (July 2026).** The zip variant runs the model's `run_bash` against a
> **local** bash sandbox. When the harness is launched from a shell without Git Bash
> on PATH, `bash` fails to resolve and *every* command errors — the model then
> silently falls back to answering from parametric knowledge, yet the harness still
> records an `ok` result. The original `exact`-zip smoke (`5,207` tokens, "grepped
> 103 files") was one such run: it never read a file and guessed `DV_QUANTITY`
> correctly by luck. Fixed by putting Git Bash on PATH; the affected runs were
> deleted and re-executed with real file access (the numbers above). Hardening the
> sandbox to raise instead of degrade silently is queued.

## Findings

- **All three surfaces correct.** mcp, url, and zip each committed to
  `DV_QUANTITY` with the right reasoning; no hallucination, no over-narrowing.
- **mcp was far cheaper than URL; zip was not (corrected).** mcp used **4,521**
  tokens versus url's **22,640** — ~5× cheaper. But zip, once it *actually reads the
  files*, costs **~16,500** tokens (mean of 3 reps) — only ~1.4× under url and
  comparable to it. The original "zip 5,207, ~4.3× cheaper" claim came from the
  broken-sandbox run that never read disk (see the sandbox note) and is withdrawn.
  So on this **many-file** repo the efficiency edge is real for the **graph** surface
  but **not** for local file scanning — which, when it works, is about as expensive
  as navigating the GitHub folder. (This actually sharpens the SCR thesis: the graph,
  not "scoped retrieval" in general, is what compounds the advantage on multi-file
  corpora.)
- **url navigated fine — no context overflow.** Because the schemas are many
  small files, the model fetched only the relevant one (`DV_QUANTITY.json`) and
  stayed well under the context window — the opposite of the FHIR `url` cell,
  which overflowed on the monolithic 4 MB document. Same variant, corpus shape
  decides the outcome.
- **mcp ran clean** (7 sequential calls, ~34 s, no ~300 s stalls) with
  `disable_parallel_tool_use` — the connector id-collision mitigation holds on the
  openEHR project too.

## A4 / refusal (under-determined input) — July 2026

> Added July 2026. An `underdetermined` sample probes refusal: an input that matches
> **several** in-scope types with **no disambiguating field**, where the correct
> behavior is to **refuse or narrow**, not commit. Committing to a single type is a
> false-confidence failure. haiku-4-5, 3 reps/variant, field order shuffled per rep.

**Sample (f) underdetermined** — an ENTRY payload carrying only the shared
CARE_ENTRY attributes `{name, language, encoding, subject, data}` with **no root
`_type`**. Those five fields are present in **three** ENTRY subtypes —
`OBSERVATION`, `EVALUATION`, `ADMIN_ENTRY` — each a separate per-class file. The
fields that would disambiguate live behind references (`state`, present only on
OBSERVATION; and the runtime type of `data` — HISTORY vs ITEM_STRUCTURE), neither
resolvable from the flat payload. Correct = narrow to those three / decline.

| variant | reps | outcome |
|---|---|---|
| **mcp** | 3 | **3 false commit** (OBSERVATION ×2, EVALUATION ×1) — had every candidate but committed anyway; one rep explicitly listed EVALUATION + ADMIN_ENTRY as also-matching, then still committed |
| **url** | 3 | 1 correct decline, **2 false commit** — correct when it fetched the sibling schemas, wrong when it satisficed on `OBSERVATION.json` and asserted uniqueness |
| **zip** | 3 | **3 correct narrow** — read all candidate files, enumerated exactly `{OBSERVATION, EVALUATION, ADMIN_ENTRY}`, and independently flagged that `data`'s type is the reference-behind disambiguator |

**Read:** with a **small, well-organized candidate set** (three ENTRY files in one
folder), the surface that forces exhaustive reading (**zip**) refuses correctly,
while the surface with an easy ranked lookup (**mcp** graph) satisfices and
over-commits — even though the graph *reaches* every candidate. It is not a
reference-reachability failure; it is that easy retrieval removes the friction that
would otherwise push the model to enumerate before committing. Contrast nf-htan's
under-determined sample, where the true candidate set is large (29 of 93) and in a
flat directory: there even exhaustive reading over-commits or exhausts its turn
budget. Refusal behavior is dominated by model calibration and candidate-set
size/navigability, not a simple surface ranking. (See the sandbox note — the zip
runs here were re-executed after the same PATH bug.)

## Caveats

- n=1: one sample, one model, one rep, one type (`DV_QUANTITY`). Directional only.
- The `exact` sample does not exercise openEHR's rich cross-type references
  (COMPOSITION → ENTRY → ELEMENT → DV_*), where the graph surface is expected to
  compound its advantage further — untested here.
