---
name: schema-identification
description: >-
  Identify which schema/type in a CoreModels project best matches a JSON data
  sample — and, crucially, refuse or narrow when the sample is under-determined
  instead of guessing. Use when a user provides a data record, payload, or set of
  fields and asks "what schema/type is this?", "which model does this fit?", or
  wants a sample validated against a CoreModels project.
---

# Schema Identification with CoreModels

You are matching a JSON data sample to the types defined in a CoreModels project
(a typed schema graph). A project has **types** (classes/schemas), **elements**
(fields, shared across types), and **taxonomies** (controlled-vocabulary value
sets). A type is linked to each of its fields by a **"Domain Includes"** relation.

## The one rule that matters most

**Enumerate every candidate before you commit.** The graph makes it easy to find
*a* type that contains a field and stop there — that is the main way this task goes
wrong. A field almost never belongs to only one type. You have not identified a
schema until you have checked which *other* types also contain *all* the sample's
fields. Finding that `TypeX` contains all the fields is **not** sufficient; you must
also confirm no other type does.

## Tools

- `get_project_summary` — list the project's types, elements, taxonomies (labels +
  ids). Orient here first. It paginates; page through if needed.
- `search_nodes` — find a specific element or type by name/text.
- `get_mixins_and_relation_groups` — see the relation groups (including
  "Domain Includes" that ties a type to its fields).
- `export_jsonschema` — export a candidate type's full JSON Schema.
- `validate_json` — validate the sample against a specific type. Use this to
  confirm a commit, not to search.

## Method

1. **Extract the fields.** List the top-level keys of the sample. Note any nested
   objects and any `_type`/discriminator hints (but do not trust a discriminator
   blindly — verify it).
2. **Map each field to its element(s).** For each field, `search_nodes` to find the
   matching element node and record its id.
3. **Find the types that include each field.** For each element, look at its
   "Domain Includes" relations to collect the set of types that contain it. (A
   type's outgoing "Domain Includes" = its field list; an element's incoming ones =
   the types that use it.)
4. **Intersect.** The candidate set is the types that contain **all** the sample's
   fields — the intersection of the per-field type sets. This intersection is the
   answer to "how determined is this sample", so compute it explicitly. Do not skip
   it because one type looked right.
5. **Check values, not just field names.** If a field maps to a taxonomy
   (controlled vocabulary), confirm the sample's value is actually in that taxonomy.
   A field-name match with an out-of-vocabulary value is a weaker match and may rule
   a type out.
6. **Resolve reference-behind disambiguators.** If two candidates share every
   top-level field but differ in the *type* of a nested field (e.g. one expects
   `data` to be a `HISTORY`, another an `ITEM_STRUCTURE`), export those types and
   compare the nested structure to disambiguate. If the sample doesn't carry enough
   nested detail to decide, it stays under-determined — say so.

## Decision rule

- **Exactly one candidate** contains all fields (and values check out): **commit.**
  Name the type, cite its node id, and validate with `validate_json`.
- **More than one candidate:** **do not pick one.** Return the candidate list and
  name the specific field or value that *would* disambiguate ("add `state` to
  distinguish OBSERVATION; provide `bodySite` to distinguish BiospecimenTemplate").
  Ask for it or state plainly that the input is under-determined.
- **No candidate** contains all fields: say there is no matching type in the
  project. Do not invent one, and do not force-fit the closest partial match.

Prefer under-claiming to over-claiming. "These three types all fit; I need X to
choose" is a correct and useful answer — a confident wrong commit is not.

## Worked example

Sample: `{ "individualID": ..., "specimenID": ..., "aliquotID": ... }`

1. Fields: individualID, specimenID, aliquotID.
2. `search_nodes` finds each as an element.
3. "Domain Includes" relations show **individualID** is used by BiospecimenTemplate
   *and* ~28 assay templates; likewise specimenID and aliquotID.
4. Intersection = ~29 types. **Under-determined.**
5. Correct answer: *"These are shared identifier fields present in ~29 templates
   (BiospecimenTemplate plus assay templates). There is no field here that selects
   one — e.g. `bodySite` would point to BiospecimenTemplate, an assay-specific field
   would point elsewhere. Which did you intend?"*
   A commit to BiospecimenTemplate here would be wrong, even though it is the most
   familiar match.

## Failure modes to avoid

- **Satisficing:** committing to the first type that contains the fields without
  checking the others. This is the most common error — the enumeration step exists
  to prevent it.
- **Committing through visible ambiguity:** if you have already seen that several
  types match, listing them and then committing to one anyway is the same error.
- **Answering from memory:** if the tools fail or return nothing, say so and stop —
  never fall back to what you "know" the schema probably is.
- **Trusting a discriminator you didn't verify:** a `_type` hint can be absent,
  wrong, or ambiguous; confirm against the project.