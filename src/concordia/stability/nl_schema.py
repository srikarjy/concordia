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
SPECIFICITY = ("actionable", "underspecified")

EXTRACTION_SYSTEM_PROMPT = """You extract only what the user explicitly said.

Return exactly the requested JSON object and no prose.

Intent values (apply this precedence when more than one description fits):
- stability_prediction: the user asks about measured folding stability or mutation effects.
  Positive example: "score the measured stability of A13Q". Negative example: "fold this sequence".
- structure_prediction: the user asks for a predicted three-dimensional structure or fold.
  Positive example: "predict the structure". Negative example: "rank measured stability".
- constraint_inspection: the user asks about protected, binding, catalytic, or constrained sites.
  Positive example: "inspect the binding site". Negative example: "score an unannotated mutation".
- general_review: the user asks for help without naming a specific scientific operation.
  Positive example: "help me with this protein". Negative example: "predict the structure".

Precedence is constraint_inspection first, then structure_prediction, then
stability_prediction, then general_review. For example, "score the protected
mutation" is constraint_inspection because the protected-site question determines
the safety dispatch before scoring.

Specificity is actionable only when every requested mutation has both a transcribed
position and a one-letter destination amino acid. A position-only request is
underspecified even though it contains a number. Never infer a position that the user did not state.
Transcribe every stated position as an integer. Convert a spelled-out amino-acid
name to its one-letter code only when it is clearly attached to a stated mutation.
For a multi-mutant, put every named substitution in mutations; do not decide whether
the backend will accept it. Leave mutations empty when only positions are named.
Use an empty positions list when the user names no position.

Examples:
User: "Score alanine at position 13 for measured stability."
JSON: {"intent":"stability_prediction","target":{"positions":[13],
"mutations":[{"position":13,"to_aa":"A"}]},"specificity":"actionable"}
User: "Evaluate A13Q plus L52Y together."
JSON: {"intent":"stability_prediction","target":{"positions":[13,52],
"mutations":[{"position":13,"to_aa":"Q"},{"position":52,"to_aa":"Y"}]},
"specificity":"actionable"}
User: "Help me with this protein."
JSON: {"intent":"general_review","target":{"positions":[],"mutations":[]},
"specificity":"underspecified"}
User: "Inspect the protected binding site at position 64."
JSON: {"intent":"constraint_inspection","target":{"positions":[64],
"mutations":[]},"specificity":"underspecified"}
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


def _expected_intent(utterance: str) -> str:
    """Apply the documented lexical precedence deterministically."""
    lowered = utterance.lower()
    if any(
        term in lowered
        for term in (
            "protected",
            "binding site",
            "binding-site",
            "catalytic",
            "constraint",
            "curated site",
        )
    ):
        return "constraint_inspection"
    if any(term in lowered for term in ("structure", "fold", "three-dimensional", "3d")):
        return "structure_prediction"
    if any(
        term in lowered
        for term in (
            "stability",
            "stable",
            "ddg",
            "mutation",
            "mutant",
            "variant",
            "substitution",
            "score",
        )
    ):
        return "stability_prediction"
    return "general_review"


def _position_is_grounded(utterance: str, position: int) -> bool:
    """Accept a literal number without allowing it to be part of a larger number."""
    return re.search(rf"(?<!\d){position}(?!\d)", utterance) is not None


def validate_extraction_response(
    response: object,
    schema: dict[str, Any],
    mutable_positions: Collection[int],
    *,
    utterance: str,
) -> None:
    """Validate shape, enum values, and manifest-scoped residue positions."""
    if not isinstance(response, dict):
        raise ValueError("extraction response must be an object")
    required = set(schema["required"])
    if set(response) != required:
        raise ValueError("extraction response must contain exactly the required fields")
    if response["intent"] not in INTENTS or response["specificity"] not in SPECIFICITY:
        raise ValueError("invalid extraction enum")
    if response["intent"] != _expected_intent(utterance):
        raise ValueError("intent does not follow the documented precedence for the utterance")
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
    if any(not _position_is_grounded(utterance, value) for value in positions):
        raise ValueError("target position was not literally present in the utterance")
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
        if not _position_is_grounded(utterance, position):
            raise ValueError("mutation position was not literally present in the utterance")
        mutation_positions.append(position)
    if not set(mutation_positions).issubset(positions):
        raise ValueError("mutation positions must also appear in target.positions")
    expected_specificity = "actionable" if mutations else "underspecified"
    if response["specificity"] != expected_specificity:
        raise ValueError("specificity must reflect whether a complete mutation is actionable")
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
    """Compatibility wrapper while callers migrate to the new extraction contract."""
    return extraction_schema()


def validate_enum_response(response: object, schema: dict[str, Any], *, utterance: str) -> None:
    """Validate a migrated caller using the new extraction contract."""
    validate_extraction_response(response, schema, range(1, 75), utterance=utterance)


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
    "validate_enum_response",
    "validate_extraction_response",
]
