"""Strict adapter boundary for externally executed Evo2 forward scores."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from concordia.genomics.evo2 import SequenceScore
from concordia.genomics.schema import GenomicSequence


class Evo2ForwardRunner(Protocol):
    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, Any]: ...


@runtime_checkable
class _SupportsPreflight(Protocol):
    """A runner that can reject a sequence without executing a forward pass."""

    def preflight(self, sequence: GenomicSequence) -> None: ...


class RealEvo2Scorer:
    """Validate a caller-supplied Evo2 execution; never silently falls back to a fixture."""

    def __init__(self, runner: Evo2ForwardRunner, *, checkpoint: str, target: str):
        if not checkpoint.strip() or not target.strip():
            raise ValueError("checkpoint and scoring target are required")
        self.runner = runner
        self.model_id = checkpoint
        self.target = target

    def preflight(self, sequence: GenomicSequence) -> None:
        """Delegate cheap input validation to runners that implement it.

        Callers use this to reject a sequence before spending a quota slot.
        A runner without ``preflight`` validates inside ``score`` instead, so
        this is a no-op rather than an error.
        """

        if isinstance(self.runner, _SupportsPreflight):
            self.runner.preflight(sequence)

    def score(self, sequence: GenomicSequence) -> SequenceScore:
        raw = self.runner.score(sequence, checkpoint=self.model_id, target=self.target)
        result = SequenceScore.model_validate(raw)
        if result.model_id != self.model_id or result.target != self.target:
            raise ValueError("Evo2 output identity does not match the declared adapter scope")
        if result.sequence_hash != sequence.content_hash():
            raise ValueError("Evo2 output sequence hash does not match the input sequence")
        if result.execution_mode not in {"real", "recorded_real"}:
            raise ValueError("real Evo2 adapter refuses fixture or synthetic execution modes")
        if not result.scientific_use_allowed:
            raise ValueError("Evo2 output is not eligible for scientific use")
        return result
