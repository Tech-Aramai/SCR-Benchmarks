"""LLM-as-judge grader.

Uses `client.messages.parse()` with a Pydantic schema for validated structured
output — no regex parsing of the assistant's prose.
"""
from __future__ import annotations

import json
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field


Behavior = Literal["commit", "narrow", "decline", "flag_inconsistency", "error"]


class GraderVerdict(BaseModel):
    """Structured verdict returned by the grader model."""

    predicted_behavior: Behavior
    predicted_schema: str | None = None
    predicted_candidates: list[str] = Field(default_factory=list)
    cited_id_or_path: str | None = None
    correct: bool
    hallucinated: bool
    notes: str = ""


GRADER_SYSTEM_PROMPT_TEMPLATE = """You are grading a schema-identification answer.

The schema universe in scope for this benchmark is: {universe}.

You will be given:
- The sample type: exact | ambiguous | foreign | chimeric
- The full `expected` block, which always includes a `behavior` and may include
  additional fields (`schema_name`, `schema_namespace`, `node_id`,
  `wrong_but_tempting`, `disambiguator_field`, `candidate_schemas`, `grading_note`)
- The sample payload that was given to the assistant
- The assistant's final answer text

Grading rules:

1. If `expected.grading_note` is present, follow it precisely — it overrides
   the general rules below.

2. Otherwise: `correct` is true iff `predicted_behavior` matches
   `expected.behavior` AND:
   - for `commit`: `predicted_schema` names the expected schema. Accept
     reasonable identifier forms — a human-readable schema name, a namespaced
     id, and the matching `node_id` all denote the same schema.
   - for `narrow` / `flag_inconsistency`: `predicted_candidates` includes all
     schemas listed in `expected.candidate_schemas`.
   - for `decline`: the assistant did not commit to any schema and stated no
     match was found.

3. `hallucinated` is true iff:
   - the assistant committed to a schema in `expected.wrong_but_tempting`, OR
   - the assistant committed when `expected.behavior` was `decline`, OR
   - `predicted_schema` names a schema not present in the loaded universe
     ({universe}), OR
   - the assistant invented details (field names, namespaces, IDs) not
     derivable from the loaded schemas.

   `hallucinated` is FALSE when the assistant correctly commits on `commit`-
   typed samples, even ambiguous ones — the disambiguator is the whole point.

4. `predicted_behavior` choices:
   - `commit`: assistant named one schema as the answer
   - `narrow`: assistant returned a candidate list without committing to one
   - `decline`: assistant said no schema matches
   - `flag_inconsistency`: assistant said the input mixes schemas
   - `error`: the assistant's answer is malformed or off-topic

Be strict but fair. The note must be one sentence and should mention any
disambiguator the assistant cited."""


def _build_user_message(sample: dict[str, Any], final_text: str) -> str:
    expected = sample.get("expected", {})
    return (
        f"Sample type: {sample.get('type')}\n"
        f"Sample ID:   {sample.get('id')}\n"
        "\n"
        "Expected:\n"
        f"{json.dumps(expected, indent=2)}\n"
        "\n"
        "Sample payload (input given to the assistant):\n"
        f"{json.dumps(sample.get('payload', {}), indent=2)}\n"
        "\n"
        "Assistant's final answer:\n"
        '"""\n'
        f"{final_text}\n"
        '"""\n'
    )


def grade(
    *,
    client: anthropic.Anthropic,
    grader_model: str,
    sample: dict[str, Any],
    final_text: str,
    universe_description: str,
) -> GraderVerdict:
    """Grade one assistant answer against the sample's expected block."""
    response = client.messages.parse(
        model=grader_model,
        max_tokens=1024,
        system=GRADER_SYSTEM_PROMPT_TEMPLATE.format(universe=universe_description),
        messages=[{"role": "user", "content": _build_user_message(sample, final_text)}],
        output_format=GraderVerdict,
    )

    parsed = response.parsed_output
    if parsed is None:
        # Refusal or schema mismatch — surface as an explicit error verdict so
        # downstream metrics can count grader failures rather than crashing.
        return GraderVerdict(
            predicted_behavior="error",
            correct=False,
            hallucinated=False,
            notes="grader returned no parsed output",
        )
    return parsed
