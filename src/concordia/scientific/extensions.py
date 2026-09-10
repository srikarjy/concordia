"""Validity contracts for post-Phase-10 SAE and cross-model evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class Evo2SAEFeatureEvidence(BaseModel):
    """One sparse-autoencoder observation with model and layer provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_checkpoint: str = Field(min_length=1)
    model_output_layer: str = Field(min_length=1)
    sae_checkpoint: str = Field(min_length=1)
    sae_checkpoint_digest: str = Field(pattern=SHA256_PATTERN)
    sequence_digest: str = Field(pattern=SHA256_PATTERN)
    feature_id: int = Field(ge=0)
    positions: tuple[int, ...] = Field(min_length=1)
    activations: tuple[float, ...] = Field(min_length=1)
    activation_threshold: float = Field(ge=0)
    execution_mode: Literal["real", "recorded_real", "fixture"]
    scientific_use_allowed: bool = False

    @model_validator(mode="after")
    def validate_feature(self) -> Evo2SAEFeatureEvidence:
        if len(self.positions) != len(self.activations):
            raise ValueError("SAE positions and activations must have equal lengths")
        if len(set(self.positions)) != len(self.positions) or tuple(sorted(self.positions)) != (
            self.positions
        ):
            raise ValueError("SAE positions must be unique and sorted")
        if any(value < self.activation_threshold for value in self.activations):
            raise ValueError("SAE activations must meet the declared threshold")
        if self.execution_mode == "fixture" and self.scientific_use_allowed:
            raise ValueError("fixture SAE features cannot permit scientific use")
        return self


class CrossModelComparisonSpec(BaseModel):
    """Predeclared equivalence and independence requirements for a comparator model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    comparison_id: str = Field(min_length=1)
    primary_checkpoint: str = Field(min_length=1)
    comparator_checkpoint: str = Field(min_length=1)
    assembly: str = Field(min_length=1)
    primary_target: str = Field(min_length=1)
    comparator_target: str = Field(min_length=1)
    target_equivalence_rationale: str = Field(min_length=20)
    training_independence_evidence: str = Field(min_length=20)
    frozen: Literal[True]

    @model_validator(mode="after")
    def validate_independence(self) -> CrossModelComparisonSpec:
        if self.primary_checkpoint == self.comparator_checkpoint:
            raise ValueError("cross-model evidence requires distinct checkpoints")
        return self


class CrossModelObservation(BaseModel):
    """Real comparator output admitted only under a frozen equivalence contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    comparison_id: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    sequence_digest: str = Field(pattern=SHA256_PATTERN)
    reference_score: float
    alternate_score: float
    effect: float
    output_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    execution_mode: Literal["real", "recorded_real", "fixture"]
    scientific_use_allowed: bool = False

    @model_validator(mode="after")
    def validate_observation(self) -> CrossModelObservation:
        expected = self.alternate_score - self.reference_score
        if abs(expected - self.effect) > 1e-12:
            raise ValueError("cross-model effect does not match alternate minus reference")
        if self.execution_mode == "fixture" and self.scientific_use_allowed:
            raise ValueError("fixture cross-model output cannot permit scientific use")
        return self
