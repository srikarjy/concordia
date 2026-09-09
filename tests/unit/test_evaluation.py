import pytest

from concordia.evaluation.compare import compare_responses
from concordia.scientist.schema import ScientificClaim, ScientistResponse


def _response(confidence: float, include_mechanism: bool = True) -> ScientistResponse:
    claims = [
        ScientificClaim(
            claim_key="prediction",
            claim="The model predicts activity.",
            claim_type="prediction_statement",
            confidence=confidence,
            basis="packet_evidence",
            evidence_references=["prediction"],
            evidence_strength="moderate",
            prediction_relationship="supports",
        )
    ]
    if include_mechanism:
        claims.append(
            ScientificClaim(
                claim_key="mechanism",
                claim="A mechanism may be involved.",
                claim_type="mechanistic_hypothesis",
                confidence=0.3,
                basis="background_knowledge",
                evidence_references=[],
                evidence_strength="weak",
                prediction_relationship="uncertain",
            )
        )
    return ScientistResponse(summary="summary", claims=claims)


def test_comparison_is_keyed_and_deterministic() -> None:
    result = compare_responses(_response(0.8), _response(0.6, include_mechanism=False))
    assert result["claim_retention_rate"] == 0.5
    assert result["removed_claims"] == ["mechanism::mechanistic_hypothesis"]
    assert result["confidence_deltas"]["prediction::prediction_statement"] == pytest.approx(-0.2)
