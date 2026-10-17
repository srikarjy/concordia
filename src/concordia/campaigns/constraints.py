"""Fail-closed sequence constraints used before a design is recommended."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtectedResidue:
    position: int
    residue: str
    reason: str
    source: str = "user"


def compare_protected_residues(
    reference_sequence: str,
    candidate_sequence: str,
    protected: tuple[ProtectedResidue, ...] = (),
) -> tuple[str, ...]:
    """Return violations; positions are one-based and never silently shifted."""
    reference = "".join(reference_sequence.upper().split())
    candidate = "".join(candidate_sequence.upper().split())
    violations: list[str] = []
    for item in protected:
        if item.position < 1 or item.position > len(reference):
            violations.append(f"protected position {item.position} is outside reference")
            continue
        expected = item.residue.upper()
        actual_reference = reference[item.position - 1]
        actual_candidate = candidate[item.position - 1] if item.position <= len(candidate) else "-"
        if actual_reference != expected:
            violations.append(
                "protected position "
                f"{item.position} reference mismatch ({actual_reference}!={expected})"
            )
        elif actual_candidate != expected:
            violations.append(f"position {item.position}: {item.reason}")
    return tuple(violations)


def candidate_constraint_report(
    reference_sequence: str,
    candidate_sequence: str,
    protected_positions: tuple[int, ...] = (),
) -> dict[str, object]:
    protected = tuple(
        ProtectedResidue(
            position=position,
            residue=reference_sequence[position - 1],
            reason="user-protected residue changed",
        )
        for position in protected_positions
        if 1 <= position <= len(reference_sequence)
    )
    violations = compare_protected_residues(reference_sequence, candidate_sequence, protected)
    return {
        "status": "constraint_violation" if violations else "passed",
        "protected_positions": list(protected_positions),
        "violations": list(violations),
        "scientific_use_allowed": False,
    }


__all__ = ["ProtectedResidue", "candidate_constraint_report", "compare_protected_residues"]
