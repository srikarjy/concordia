"""Validated genomic inputs for evidence-audit workflows."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GenomicSequence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_id: str = Field(min_length=1)
    sequence: str = Field(min_length=1)
    assembly: str | None = None
    region: str | None = None
    strand: str = Field(pattern=r"^[+-]$")

    @field_validator("sequence")
    @classmethod
    def valid_dna(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        invalid = sorted(set(normalized) - set("ACGT"))
        if invalid:
            raise ValueError(f"sequence contains invalid bases: {''.join(invalid)}")
        return normalized

    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class SequenceVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=0, description="Zero-based position in the supplied sequence")
    reference: str = Field(pattern=r"^[ACGT]$")
    alternate: str = Field(pattern=r"^[ACGT]$")

    @model_validator(mode="after")
    def changes_base(self) -> SequenceVariant:
        if self.reference == self.alternate:
            raise ValueError("alternate base must differ from reference")
        return self


def apply_variant(sequence: GenomicSequence, variant: SequenceVariant) -> GenomicSequence:
    if variant.position >= len(sequence.sequence):
        raise ValueError("variant position exceeds sequence length")
    observed = sequence.sequence[variant.position]
    if observed != variant.reference:
        raise ValueError(
            f"reference mismatch at position {variant.position}: expected {observed}"
        )
    altered = (
        sequence.sequence[: variant.position]
        + variant.alternate
        + sequence.sequence[variant.position + 1 :]
    )
    return sequence.model_copy(
        update={
            "sequence_id": (
                f"{sequence.sequence_id}:{variant.position}"
                f"{variant.reference}>{variant.alternate}"
            ),
            "sequence": altered,
        }
    )
