"""Validation-first contracts for antibody design workflows.

These contracts intentionally describe inputs to a workflow, not therapeutic
claims. Model-specific generation and structure prediction are external
execution steps and must record their own model/checkpoint provenance.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AMINO_ACIDS = frozenset("ARNDCQEGHILKMFPSTWYV")
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class AntibodyRole(StrEnum):
    HEAVY = "heavy"
    LIGHT = "light"
    NANOBODY = "nanobody"


class AntibodyNumberingScheme(StrEnum):
    IMGT = "imgt"
    KABAT = "kabat"
    CHOTHIA = "chothia"
    AHO = "aho"


class AntibodyChain(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chain_id: str = Field(min_length=1, max_length=4, pattern=r"^[A-Za-z0-9]+$")
    role: AntibodyRole
    sequence: str = Field(min_length=1, max_length=4_096)
    numbering_scheme: AntibodyNumberingScheme = AntibodyNumberingScheme.IMGT

    @field_validator("sequence")
    @classmethod
    def normalize_sequence(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        if not normalized:
            raise ValueError("antibody sequence must not be empty")
        invalid = sorted(set(normalized) - AMINO_ACIDS)
        if invalid:
            raise ValueError(
                "antibody sequence contains non-standard amino acids: "
                + "".join(invalid)
            )
        return normalized


class AntibodyDesignRequest(BaseModel):
    """Input shared by validation and future antibody-design adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["antibody_design"] = "antibody_design"
    chains: tuple[AntibodyChain, ...] = Field(min_length=1, max_length=2)
    antigen_sequence: str | None = Field(default=None, max_length=4_096)
    antigen_structure_artifact_digest: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    epitope_residues: tuple[int, ...] = Field(default_factory=tuple, max_length=512)
    generation_model: str = Field(default="rfantibody", min_length=1, max_length=100)
    sequence_model: str = Field(default="proteinmpnn", min_length=1, max_length=100)
    structure_model: str = Field(default="boltz2", min_length=1, max_length=100)
    seed: int | None = Field(default=None, ge=0)

    @field_validator("antigen_sequence")
    @classmethod
    def normalize_antigen_sequence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(value.upper().split())
        if not normalized:
            raise ValueError("antigen_sequence must not be empty when provided")
        invalid = sorted(set(normalized) - AMINO_ACIDS)
        if invalid:
            raise ValueError(
                "antigen sequence contains non-standard amino acids: "
                + "".join(invalid)
            )
        return normalized

    @field_validator("epitope_residues")
    @classmethod
    def validate_epitope_residues(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value):
            raise ValueError("epitope_residues must not contain duplicates")
        if any(residue < 0 for residue in value):
            raise ValueError("epitope_residues must use zero-based non-negative positions")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_design_inputs(self) -> AntibodyDesignRequest:
        roles = [chain.role for chain in self.chains]
        if AntibodyRole.NANOBODY in roles and len(self.chains) != 1:
            raise ValueError("nanobody designs must contain exactly one chain")
        if AntibodyRole.NANOBODY not in roles and set(roles) != {
            AntibodyRole.HEAVY,
            AntibodyRole.LIGHT,
        }:
            raise ValueError(
                "paired antibody designs require exactly one heavy and one light chain"
            )
        if self.antigen_sequence is None and self.antigen_structure_artifact_digest is None:
            raise ValueError("provide antigen_sequence or antigen_structure_artifact_digest")
        if self.antigen_sequence is not None and any(
            residue >= len(self.antigen_sequence) for residue in self.epitope_residues
        ):
            raise ValueError("epitope_residues contains a position outside antigen_sequence")
        return self


class AntibodyValidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["antibody_validation"] = "antibody_validation"
    chain_ids: tuple[str, ...]
    roles: tuple[AntibodyRole, ...]
    chain_lengths: dict[str, int]
    numbering_scheme: AntibodyNumberingScheme
    epitope_residues: tuple[int, ...]
    validation_status: Literal["VALID"] = "VALID"
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Validation confirms contract and sequence integrity only.",
        "CDR boundaries require an actual numbering tool such as ANARCI or AbNumber.",
        "No antibody generation, binding prediction, or therapeutic conclusion was performed.",
    )


def validate_antibody(request: AntibodyDesignRequest) -> AntibodyValidateOutput:
    """Perform deterministic input validation without network or model execution."""

    return AntibodyValidateOutput(
        chain_ids=tuple(chain.chain_id for chain in request.chains),
        roles=tuple(chain.role for chain in request.chains),
        chain_lengths={chain.chain_id: len(chain.sequence) for chain in request.chains},
        numbering_scheme=request.chains[0].numbering_scheme,
        epitope_residues=request.epitope_residues,
    )
