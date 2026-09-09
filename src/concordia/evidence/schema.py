"""Versioned, validated evidence packet models."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: str = Field(min_length=1)
    value: FiniteFloat
    rank: int = Field(ge=1)
    direction: Literal["positive", "negative"]


class ExplanationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["tree_shap"]
    version: str = Field(min_length=1)
    output: Literal["positive_class_probability"]
    feature_count: int = Field(gt=0)
    attributions: tuple[FiniteFloat, ...] = Field(min_length=1)
    top_positive: tuple[Attribution, ...] = ()
    top_negative: tuple[Attribution, ...] = ()

    @field_validator("attributions")
    @classmethod
    def finite_attributions(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Attributions must be finite")
        return values


class PredictionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    assay: str = Field(min_length=1)
    probability: FiniteFloat = Field(ge=0.0, le=1.0)
    predicted_label: Literal[0, 1]


class DocumentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidencePacket(BaseModel):
    """Agent-visible packet; intervention provenance is kept outside this model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    packet_id: str = Field(min_length=1)
    molecule_id: str = Field(min_length=1)
    canonical_smiles: str = Field(min_length=1)
    prediction: PredictionEvidence
    explanation: ExplanationEvidence | None = None
    documents: tuple[DocumentEvidence, ...] = ()

    @field_validator("canonical_smiles")
    @classmethod
    def no_whitespace(cls, value: str) -> str:
        if value != value.strip() or any(char.isspace() for char in value):
            raise ValueError("canonical_smiles must not contain whitespace")
        return value

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def as_agent_dict(self) -> dict[str, object]:
        """Return only evidence visible to the scientist prompt."""
        return json.loads(self.canonical_json())
