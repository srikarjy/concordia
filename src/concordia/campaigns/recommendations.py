"""Reproducible, model-agnostic selection policies for campaign rounds."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionCandidate:
    candidate_id: str
    score: float | None = None
    sequence: str = ""
    is_reference: bool = False
    measured: bool = False
    uncertainty: float | None = None
    constraint_violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectionResult:
    policy: str
    candidate_ids: tuple[str, ...]
    rationale: dict[str, object]


def select_candidates(
    candidates: tuple[SelectionCandidate, ...],
    *,
    policy: str,
    batch_size: int,
    seed: int = 0,
    reference_candidate_id: str | None = None,
    require_measured: bool = False,
    max_uncertainty: float | None = None,
) -> SelectionResult:
    """Select a batch with a fully recorded deterministic policy.

    ``None`` scores are never treated as zero: greedy and uncertainty policies
    report insufficient signal instead of silently promoting unmeasured rows.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise ValueError("candidate IDs must be unique")
    if batch_size > len(candidates):
        raise ValueError("batch_size cannot exceed candidate count")
    violations = {
        candidate.candidate_id: candidate.constraint_violations
        for candidate in candidates
        if candidate.constraint_violations
    }
    if violations:
        raise ValueError("constraint violation: " + "; ".join(
            f"{candidate_id} ({', '.join(reasons)})" for candidate_id, reasons in violations.items()
        ))
    if require_measured and any(not candidate.measured for candidate in candidates):
        raise ValueError("insufficient evidence: every candidate must have a measurement")
    if max_uncertainty is not None and any(
        candidate.uncertainty is None or candidate.uncertainty > max_uncertainty
        for candidate in candidates
    ):
        raise ValueError(
            "insufficient evidence: candidate uncertainty exceeds the configured limit"
        )
    if policy == "random":
        ordered = list(candidates)
        random.Random(seed).shuffle(ordered)
        selected = ordered[:batch_size]
    elif policy == "greedy":
        if any(candidate.score is None for candidate in candidates):
            raise ValueError("greedy policy requires a score for every candidate")
        scored = [candidate for candidate in candidates if candidate.score is not None]
        selected = sorted(scored, key=lambda item: (-item.score, item.candidate_id))[  # type: ignore[operator]
            :batch_size
        ]
    elif policy == "uncertainty":
        if any(candidate.score is None for candidate in candidates):
            raise ValueError("uncertainty policy requires a score for every candidate")
        scored = [candidate for candidate in candidates if candidate.score is not None]
        selected = sorted(scored, key=lambda item: (item.score, item.candidate_id))[  # type: ignore[misc]
            :batch_size
        ]
    elif policy == "diversity":
        selected = _diversity_selection(candidates, batch_size, seed)
    else:
        raise ValueError(f"unsupported selection policy: {policy}")
    if reference_candidate_id is not None:
        reference = next(
            (
                candidate
                for candidate in candidates
                if candidate.candidate_id == reference_candidate_id
            ),
            None,
        )
        if reference is None:
            raise ValueError("reference candidate is not present in selection candidates")
        if reference not in selected:
            selected[-1] = reference
    return SelectionResult(
        policy=policy,
        candidate_ids=tuple(candidate.candidate_id for candidate in selected),
        rationale={
            "policy": policy,
            "seed": seed,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "scientific_use_allowed": False,
            "evidence_status": "ready_for_experimental_review" if any(
                candidate.is_reference for candidate in candidates
            ) else "needs_more_evidence",
            "reference_candidate_id": reference_candidate_id,
            "reference_included": any(
                candidate.candidate_id == reference_candidate_id or candidate.is_reference
                for candidate in selected
            ),
        },
    )


def _diversity_selection(
    candidates: tuple[SelectionCandidate, ...], batch_size: int, seed: int
) -> list[SelectionCandidate]:
    """Greedy max-min sequence diversity with a stable tie-break."""
    ranked = sorted(candidates, key=lambda item: _tie_break(seed, item.candidate_id))
    selected = [ranked[0]]
    while len(selected) < batch_size:
        remaining = [candidate for candidate in ranked if candidate not in selected]
        selected.append(
            max(
                remaining,
                key=lambda candidate: (
                    min(
                        _sequence_distance(candidate.sequence, chosen.sequence)
                        for chosen in selected
                    ),
                    _tie_break(seed, candidate.candidate_id),
                ),
            )
        )
    return selected


def _sequence_distance(left: str, right: str) -> int:
    overlap = sum(a != b for a, b in zip(left, right, strict=False))
    return overlap + abs(len(left) - len(right))


def _tie_break(seed: int, candidate_id: str) -> str:
    return hashlib.sha256(f"{seed}:{candidate_id}".encode()).hexdigest()


__all__ = ["SelectionCandidate", "SelectionResult", "select_candidates"]
