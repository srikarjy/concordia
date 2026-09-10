"""Transparent, deterministic colony fitness calculation."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FitnessObservation(BaseModel):
    """Saved measurements used by the evaluator; never model-assigned truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    provenance_completeness: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    counterfactual_consistency: float = Field(ge=0, le=1)
    attribution_direction_agreement: float = Field(ge=0, le=1)
    cross_verification_coverage: float = Field(ge=0, le=1)
    valid_citation_rate: float = Field(ge=0, le=1)
    schema_valid_response_rate: float = Field(ge=0, le=1)
    repeated_run_stability: float = Field(ge=0, le=1)
    tool_success_rate: float = Field(ge=0, le=1)
    runtime_seconds: float = Field(ge=0)
    token_usage: int = Field(ge=0)
    compute_usage: float = Field(ge=0)
    unsupported_claim_penalty: float = Field(ge=0, le=1)
    contradiction_penalty: float = Field(ge=0, le=1)
    tool_failure_penalty: float = Field(ge=0, le=1)


class FitnessVector(FitnessObservation):
    """Complete fitness vector retained with every selection decision."""


class FitnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    policy_version: Literal["weighted-fitness-v1"] = "weighted-fitness-v1"
    runtime_reference_seconds: float = Field(default=120, gt=0)
    token_reference: int = Field(default=2_048, gt=0)
    compute_reference: float = Field(default=4, gt=0)


class FitnessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    vector: FitnessVector
    weighted_score: float = Field(ge=0, le=1)
    rationale: tuple[str, ...]


QUALITY_WEIGHTS = {
    "provenance_completeness": 0.18,
    "evidence_coverage": 0.12,
    "counterfactual_consistency": 0.12,
    "attribution_direction_agreement": 0.08,
    "cross_verification_coverage": 0.10,
    "valid_citation_rate": 0.06,
    "schema_valid_response_rate": 0.14,
    "repeated_run_stability": 0.10,
    "tool_success_rate": 0.10,
}
PENALTY_WEIGHTS = {
    "unsupported_claim_penalty": 0.12,
    "contradiction_penalty": 0.12,
    "tool_failure_penalty": 0.08,
}


def evaluate_fitness(
    observation: FitnessObservation, policy: FitnessPolicy | None = None
) -> FitnessResult:
    """Apply a documented weighted policy to an immutable observation."""

    policy = policy or FitnessPolicy()
    vector = FitnessVector.model_validate(observation.model_dump(mode="json"))
    quality = sum(getattr(vector, name) * weight for name, weight in QUALITY_WEIGHTS.items())
    penalties = sum(getattr(vector, name) * weight for name, weight in PENALTY_WEIGHTS.items())
    resource_penalty = 0.04 * min(vector.runtime_seconds / policy.runtime_reference_seconds, 1)
    resource_penalty += 0.04 * min(vector.token_usage / policy.token_reference, 1)
    resource_penalty += 0.04 * min(vector.compute_usage / policy.compute_reference, 1)
    score = round(max(0.0, min(1.0, quality - penalties - resource_penalty)), 8)
    payload = json.dumps(
        observation.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return FitnessResult(
        observation_digest=hashlib.sha256(payload).hexdigest(),
        policy_version=policy.policy_version,
        vector=vector,
        weighted_score=score,
        rationale=(
            "quality components use declared weighted-fitness-v1 weights",
            "scientific, tool-failure, and normalized resource penalties are subtracted",
            "ties are resolved by immutable member identifier",
        ),
    )
