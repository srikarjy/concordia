"""Structured scientist-agent responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimType = Literal[
    "prediction_statement",
    "attribution_interpretation",
    "structure_observation",
    "mechanistic_hypothesis",
    "assay_interpretation",
    "risk_extrapolation",
    "limitation",
]
ClaimBasis = Literal["packet_evidence", "background_knowledge", "both"]
PredictionRelationship = Literal["supports", "opposes", "neutral", "uncertain"]
EvidenceStrength = Literal["none", "weak", "moderate", "strong"]


class ScientificClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_key: str = Field(min_length=1, max_length=120)
    claim: str = Field(min_length=1, max_length=2000)
    claim_type: ClaimType
    confidence: float = Field(ge=0.0, le=1.0)
    basis: ClaimBasis
    evidence_references: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength
    prediction_relationship: PredictionRelationship


class ScientistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    summary: str = Field(min_length=1, max_length=3000)
    claims: list[ScientificClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
