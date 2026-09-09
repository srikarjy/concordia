"""Evo2-compatible scoring boundary with an explicit recorded-fixture mode."""

from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from concordia.genomics.schema import GenomicSequence


class SequenceScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    execution_mode: str
    sequence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: float = Field(allow_inf_nan=False)
    target: str
    scientific_use_allowed: bool


class SequenceScorer(Protocol):
    model_id: str

    def score(self, sequence: GenomicSequence) -> SequenceScore: ...


class RecordedFixtureScorer:
    """Deterministic software fixture; never valid as scientific evidence."""

    model_id = "evo2-recorded-fixture-v1"

    def score(self, sequence: GenomicSequence) -> SequenceScore:
        digest = hashlib.sha256(sequence.sequence.encode("ascii")).digest()
        score = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        return SequenceScore(
            model_id=self.model_id,
            execution_mode="recorded_fixture",
            sequence_hash=sequence.content_hash(),
            score=score,
            target="software_contract_only",
            scientific_use_allowed=False,
        )
