"""Typed extraction and deterministic prose contracts for the local model.

The extraction path may contain digits only in explicitly transcribed residue
positions. Those integers are validated against the manifest's mutable-position
set before they reach the backend. Intent, specificity, and amino-acid fields
remain non-numeric enum values. The prose path keeps the stronger invariant:
model-emitted prose fields contain no digits at all; deterministic Python code
fills every numeric slot after extraction.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

AMINO_ACIDS = tuple("ACDEFGHIKLMNPQRSTVWY")
INTENTS = (
    "stability_prediction",
    "structure_prediction",
    "constraint_inspection",
    "general_review",
)
SPECIFICITY = ("targeted", "underspecified")

EXTRACTION_SYSTEM_PROMPT = """You extract only what the user explicitly said.

Return exactly the requested JSON object and no prose.

Intent values:
- stability_prediction: the user asks about measured folding stability or mutation effects.
  Positive example: "score the measured stability of A13Q". Negative example: "fold this sequence".
- structure_prediction: the user asks for a predicted three-dimensional structure or fold.
  Positive example: "predict the structure". Negative example: "rank measured stability".
- constraint_inspection: the user asks about protected, binding, catalytic, or constrained sites.
  Positive example: "inspect the binding site". Negative example: "score an unannotated mutation".
- general_review: the user asks for help without naming a specific scientific operation.
  Positive example: "help me with this protein". Negative example: "predict the structure".

Specificity is targeted when the utterance names a residue position or substitution;
otherwise it is underspecified. Never infer a position that the user did not state.
Transcribe every stated position as an integer. Convert a spelled-out amino-acid
name to its one-letter code only when it is clearly attached to a stated mutation.
For a multi-mutant, put every named substitution in mutations; do not decide whether
the backend will accept it. Leave mutations empty when only positions are named.
Use an empty positions list when the user names no position.

Examples:
User: "Score alanine at position 13 for measured stability."
JSON: {"intent":"stability_prediction","target":{"positions":[13],
"mutations":[{"position":13,"to_aa":"A"}]},"specificity":"targeted"}
User: "Evaluate A13Q plus L52Y together."
JSON: {"intent":"stability_prediction","target":{"positions":[13,52],
"mutations":[{"position":13,"to_aa":"Q"},{"position":52,"to_aa":"Y"}]},
"specificity":"targeted"}
User: "Help me with this protein."
JSON: {"intent":"general_review","target":{"positions":[],"mutations":[]},
"specificity":"underspecified"}
User: "Inspect the protected binding site at position 64."
JSON: {"intent":"constraint_inspection","target":{"positions":[64],
"mutations":[]},"specificity":"targeted"}
"""


def extraction_schema() -> dict[str, Any]:
    """Return the typed extraction schema used by Ollama."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"enum": list(INTENTS)},
            "target": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "positions": {"type": "array", "items": {"type": "integer"}},
                    "mutations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "position": {"type": "integer"},
                                "to_aa": {"enum": list(AMINO_ACIDS)},
                            },
                            "required": ["position", "to_aa"],
                        },
                    },
                },
                "required": ["positions", "mutations"],
            },
            "specificity": {"enum": list(SPECIFICITY)},
        },
        "required": ["intent", "target", "specificity"],
    }


def validate_extraction_response(
    response: object, schema: dict[str, Any], mutable_positions: Collection[int]
) -> None:
    """Validate shape, enum values, and manifest-scoped residue positions."""
    if not isinstance(response, dict):
        raise ValueError("extraction response must be an object")
    required = set(schema["required"])
    if set(response) != required:
        raise ValueError("extraction response must contain exactly the required fields")
    if response["intent"] not in INTENTS or response["specificity"] not in SPECIFICITY:
        raise ValueError("invalid extraction enum")
    target = response["target"]
    if not isinstance(target, dict) or set(target) != {"positions", "mutations"}:
        raise ValueError("target must contain positions and mutations")
    allowed = set(mutable_positions)
    positions = target["positions"]
    mutations = target["mutations"]
    if not isinstance(positions, list) or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in positions
    ):
        raise ValueError("target.positions must contain integers")
    if len(set(positions)) != len(positions):
        raise ValueError("target.positions must not contain duplicates")
    if any(value not in allowed for value in positions):
        raise ValueError("target position is outside the manifest mutable range")
    if not isinstance(mutations, list):
        raise ValueError("target.mutations must be a list")
    mutation_positions: list[int] = []
    for mutation in mutations:
        if not isinstance(mutation, dict) or set(mutation) != {"position", "to_aa"}:
            raise ValueError("each mutation must contain position and to_aa")
        position = mutation["position"]
        to_aa = mutation["to_aa"]
        if not isinstance(position, int) or isinstance(position, bool) or position not in allowed:
            raise ValueError("mutation position is outside the manifest mutable range")
        if not isinstance(to_aa, str) or to_aa not in AMINO_ACIDS:
            raise ValueError("mutation to_aa must be one standard amino-acid letter")
        mutation_positions.append(position)
    if not set(mutation_positions).issubset(positions):
        raise ValueError("mutation positions must also appear in target.positions")
    for value in (response["intent"], response["specificity"]):
        if re.search(r"\d", str(value)):
            raise ValueError("non-position extraction fields cannot contain digits")


def extraction_digits_in_non_position_fields(response: object) -> bool:
    """Return whether a response emits digits outside permitted position integers."""
    if not isinstance(response, dict):
        return True
    target = response.get("target")
    if not isinstance(target, dict):
        return True
    values = [response.get("intent"), response.get("specificity")]
    for mutation in target.get("mutations", []):
        if isinstance(mutation, dict):
            values.append(mutation.get("to_aa"))
    return any(re.search(r"\d", str(value)) for value in values)


def enum_only_schema(_tool_names: list[str]) -> dict[str, Any]:
    """Compatibility import for legacy entry points; return the new schema."""
    return extraction_schema()


def validate_enum_response(_response: object, _schema: dict[str, Any]) -> None:
    """Fail explicitly when an old action/tool/evidence caller is still invoked."""
    raise ValueError(
        "legacy action/tool/evidence extraction is removed; "
        "use validate_extraction_response"
    )


def render_numeric_recommendation(
    response: dict[str, Any], *, score: float | None, sigma: float | None
) -> str:
    """Assemble figures in Python after validation; the model never emits them."""
    if score is None or sigma is None:
        raise ValueError("numeric recommendation slots must be filled by deterministic code")
    return (
        f"Intent: {response['intent']}; score: {float(score):.4f}; "
        f"sigma: {float(sigma):.4f}"
    )


__all__ = [
    "AMINO_ACIDS",
    "EXTRACTION_SYSTEM_PROMPT",
    "INTENTS",
    "SPECIFICITY",
    "extraction_digits_in_non_position_fields",
    "extraction_schema",
    "render_numeric_recommendation",
    "validate_extraction_response",
]
