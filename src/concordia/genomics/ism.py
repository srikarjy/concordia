"""Deterministic in-silico mutagenesis against a declared sequence scorer."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from concordia.genomics.evo2 import SequenceScorer
from concordia.genomics.schema import GenomicSequence, SequenceVariant, apply_variant


class MutationEffect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=0)
    reference: str
    alternate: str
    reference_score: float = Field(allow_inf_nan=False)
    alternate_score: float = Field(allow_inf_nan=False)
    delta: float = Field(allow_inf_nan=False)
    reference_artifact_hash: str
    alternate_artifact_hash: str
    scientific_use_allowed: bool


def scan_position(
    sequence: GenomicSequence, position: int, scorer: SequenceScorer
) -> tuple[MutationEffect, ...]:
    if position < 0 or position >= len(sequence.sequence):
        raise ValueError("scan position exceeds sequence length")
    reference_score = scorer.score(sequence)
    reference = sequence.sequence[position]
    effects = []
    for alternate in sorted(set("ACGT") - {reference}):
        changed = apply_variant(
            sequence,
            SequenceVariant(position=position, reference=reference, alternate=alternate),
        )
        alternate_score = scorer.score(changed)
        effects.append(
            MutationEffect(
                position=position,
                reference=reference,
                alternate=alternate,
                reference_score=reference_score.score,
                alternate_score=alternate_score.score,
                delta=alternate_score.score - reference_score.score,
                reference_artifact_hash=reference_score.sequence_hash,
                alternate_artifact_hash=alternate_score.sequence_hash,
                scientific_use_allowed=(
                    reference_score.scientific_use_allowed
                    and alternate_score.scientific_use_allowed
                ),
            )
        )
    return tuple(effects)
