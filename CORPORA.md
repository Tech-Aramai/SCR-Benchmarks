# SCR Benchmark — Corpora Guide

A guide to the schema collections in the benchmark: how each is **shaped**, how
much **controlled vocabulary** it carries, and therefore **what each is good for
testing**. Different schemas surface different SCR properties — so the choice of
corpus determines which claims an experiment can actually support (see
[ROADMAP.md](ROADMAP.md)).

## At a glance

| Corpus | Standard | Shape | Controlled vocabulary | Best suited to test |
|---|---|---|---|---|
| **nf-htan** | NF-OSI + HTAN2 v1.2.0 | many small, **flat** templates; no cross-schema refs | **dense** — large value sets (ICD-10, UBERON, HGNC genes) | identification, disambiguation, **refusal**, value-grounding |
| **fhir** | HL7 FHIR R6 | **one large monolithic file**; heavy *internal* refs only | sparse inline (value sets bound externally) | **context-bloat / payload limits** |
| **openehr** | openEHR RM | many **cross-linked** files (refs to *other* documents) | minimal inline | **cross-schema reference traversal** (the compounding case) |

## The corpora in detail

### nf-htan — flat and vocabulary-dense
Two collections (**~90 standalone per-template schemas**) with **no cross-schema
references** — each template is self-contained. What makes it distinctive is its
**controlled vocabulary**: many fields are bound to large code systems (ICD-10,
UBERON anatomy, HGNC genes), so the corpus carries a very large body of enumerated
terms — **on the order of ~100,000 distinct values** once loaded into the graph.

*Good for:* the core **identification** behaviors (exact / ambiguous / foreign /
chimeric) and **refusal** under-determination (A4). Its dense vocabularies make it
the natural place to test **value-grounding** — resolving a field to the right
term — and where a graph's direct term lookup should pay off. Being flat, it does
**not** exercise reference traversal.

### fhir — one big self-contained document
A single **monolithic** JSON Schema (**~4 MB, ~890 type/definition entries**) with
heavy *internal* `$ref`s but no links to other files — the entire model arrives in
one document. Inline enumerations are sparse; FHIR binds most value sets
**externally** and expresses fixed values (e.g. `resourceType`) with `const`.

*Good for:* demonstrating the **context-bloat** failure mode — a naive
whole-document fetch blows past the model's context window, exactly the problem a
scoped retrieval surface avoids. It is *not* a reference-traversal test (everything
is in one file) nor a vocabulary test.

### openehr — cross-linked and reference-rich
**~100** per-class files connected by **~1,000 cross-file** `$ref`s (absolute URLs
to *other* schema documents), nesting from container types (`COMPOSITION`
references ~20 others, `OBSERVATION` ~30) down to leaf data values (`DV_QUANTITY`
is a 4-ref leaf). This is the only corpus where answering a question can require
**resolving a chain of references across multiple documents**.

*Good for:* the **compounding graph-traversal** case — where following edges in a
graph should beat pulling and stitching many linked files. This is the structure
the single-schema corpora can't reach.

## How CoreModels represents a corpus

When a corpus is imported into a CoreModels graph, schema **classes → Types**,
**fields → Elements**, and **controlled-vocabulary values → Taxonomy nodes**. Type
and Element counts track the source closely. Vocabulary (Taxonomy) representation
is *indicative, not a 1:1 copy* of the source enums, because of how the importer
works:

- **Taxonomies are de-duplicated** — a value used by many fields becomes a single
  Taxonomy node, so the graph holds fewer nodes than the raw number of enum values
  in the source.
- **Enums inside conditional blocks** (`if` / `then` / `else`, `anyOf` / `allOf` /
  `oneOf`) are **not** imported as Taxonomies, so those values don't appear in the
  graph at all.

So treat graph vocabulary size as a signal of *how richly a project loaded its
value sets*, not as an exact schema measurement. (It also means the same schema can
look very different across projects depending on what was loaded.)

## Samples exercised so far

| Corpus | Sample(s) | Behaviors | Status |
|---|---|---|---|
| **nf-htan** | biospecimen / disambiguation / financial / mixed-registry (+ an under-determined refusal sample) | exact · ambiguous · foreign · chimeric · underdetermined | full matrix run on the **previous HTAN2 v1.1.0** set — see [SUMMARY](corpora/nf-htan/SUMMARY.md) |
| **fhir** | LOINC lab `Observation` | exact | mcp ✅ · zip ✅ · **url ❌ context overflow** — see [SUMMARY](corpora/fhir/SUMMARY.md) |
| **openehr** | `DV_QUANTITY` | exact | all three variants ✅ — see [SUMMARY](corpora/openehr/SUMMARY.md) |

**Caveat:** the FHIR and openEHR runs so far are single-schema **leaf-type**
identification. None has yet exercised openEHR's cross-schema traversal — the
reference-rich sample (Task 2 in [ROADMAP.md](ROADMAP.md)) is what reaches that.
