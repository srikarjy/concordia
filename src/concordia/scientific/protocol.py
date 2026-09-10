"""Frozen protocol contracts for the real-validation gate."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudyStatus(StrEnum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    READY_FOR_REAL_EVIDENCE = "READY_FOR_REAL_EVIDENCE"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


class StudyProtocol(BaseModel):
    """All choices that must be fixed before inspecting study outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    protocol_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_license: str = Field(min_length=1)
    inclusion_criteria: tuple[str, ...] = Field(min_length=1)
    exclusion_criteria: tuple[str, ...] = Field(min_length=1)
    model_checkpoint: str = Field(min_length=1)
    scoring_target: str = Field(min_length=1)
    assembly: str = Field(min_length=1)
    window_size: int = Field(ge=1)
    coordinate_convention: Literal["zero_based_half_open"] = "zero_based_half_open"
    evidence_families: tuple[str, ...] = Field(min_length=2)
    hypothesis: str = Field(min_length=1)
    uncertainty_method: str = Field(min_length=1)
    status: StudyStatus = StudyStatus.DRAFT

    @model_validator(mode="after")
    def validate_protocol(self) -> StudyProtocol:
        if len(set(self.evidence_families)) != len(self.evidence_families):
            raise ValueError("evidence families must be unique")
        if not self.dataset_license.strip():
            raise ValueError("dataset license must be explicit")
        return self


class StudyVariantInput(BaseModel):
    """A reference-validated variant window selected before model scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    source_id: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://")
    transcript_hgvs: str = Field(min_length=1)
    assembly: str = Field(min_length=1)
    chromosome: str = Field(min_length=1)
    genomic_position_one_based: int = Field(ge=1)
    zero_based_position: int = Field(ge=0)
    reference: str = Field(pattern=r"^[ACGT]$")
    alternate: str = Field(pattern=r"^[ACGT]$")
    window_start: int = Field(ge=0)
    window_end: int = Field(ge=1)
    variant_offset: int = Field(ge=0)
    sequence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence_source_url: str = Field(pattern=r"^https://")
    reference_validated: Literal[True]

    @model_validator(mode="after")
    def validate_coordinates(self) -> StudyVariantInput:
        if self.genomic_position_one_based != self.zero_based_position + 1:
            raise ValueError("one-based and zero-based positions disagree")
        if self.window_end <= self.window_start:
            raise ValueError("window end must be greater than window start")
        if self.variant_offset != self.zero_based_position - self.window_start:
            raise ValueError("variant offset does not match genomic window")
        if self.variant_offset >= self.window_end - self.window_start:
            raise ValueError("variant lies outside its declared window")
        return self


class StudyInputManifest(BaseModel):
    """Frozen cohort inputs without model outcomes or selected success cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    cohort_id: str = Field(min_length=1)
    status: Literal["FROZEN"]
    frozen_at: str = Field(min_length=1)
    assembly: str = Field(min_length=1)
    coordinate_convention: Literal["zero_based_half_open"] = "zero_based_half_open"
    window_size: int = Field(ge=1)
    selection_policy: tuple[str, ...] = Field(min_length=1)
    exclusions: tuple[str, ...] = Field(min_length=1)
    data_use_terms: tuple[str, ...] = Field(min_length=1)
    variants: tuple[StudyVariantInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> StudyInputManifest:
        identifiers: set[str] = set()
        for variant in self.variants:
            if variant.source_id in identifiers:
                raise ValueError("study variant identifiers must be unique")
            identifiers.add(variant.source_id)
            if variant.assembly != self.assembly:
                raise ValueError("variant assembly does not match cohort assembly")
            if variant.window_end - variant.window_start != self.window_size:
                raise ValueError("variant window does not match cohort window size")
        return self


class ProtocolGate:
    """Deterministic gate preventing fixture artifacts from entering real studies."""

    @staticmethod
    def freeze(protocol: StudyProtocol) -> StudyProtocol:
        if protocol.status is not StudyStatus.DRAFT:
            raise ValueError("only a draft protocol can be frozen")
        return protocol.model_copy(update={"status": StudyStatus.FROZEN})

    @staticmethod
    def admit_artifact(
        protocol: StudyProtocol, *, execution_mode: str, scientific_use_allowed: bool
    ) -> None:
        if protocol.status is not StudyStatus.FROZEN:
            raise ValueError("protocol must be frozen before evidence admission")
        fixture_modes = {
            "fixture",
            "synthetic",
            "recorded_fixture",
            "deterministic_colony_fixture",
        }
        if execution_mode in fixture_modes:
            raise ValueError("fixture or synthetic artifacts cannot enter a real study")
        if not scientific_use_allowed:
            raise ValueError("artifact is not marked eligible for scientific use")
