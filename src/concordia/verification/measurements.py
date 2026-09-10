"""Scope-checked annotation overlap and repeated-run measurements."""

from __future__ import annotations

from statistics import mean, pstdev

from pydantic import Field

from concordia.verification.cross import Frozen, Scope


class RegulatoryAnnotation(Frozen):
    annotation_id: str
    assembly: str
    chromosome: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    source_url: str = Field(min_length=1)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_version: str = Field(min_length=1)
    assay: str = Field(min_length=1)


def overlap_fraction(scope: Scope, annotation: RegulatoryAnnotation) -> float:
    if annotation.end <= annotation.start:
        raise ValueError("invalid annotation interval")
    if (scope.assembly, scope.chromosome, scope.assay) != (
        annotation.assembly,
        annotation.chromosome,
        annotation.assay,
    ):
        raise ValueError("annotation assembly, chromosome, or assay mismatch")
    length = max(0, min(scope.end, annotation.end) - max(scope.start, annotation.start))
    return length / (scope.end - scope.start)


class StabilityResult(Frozen):
    count: int
    missing_count: int
    mean: float | None
    standard_deviation: float | None
    sign_agreement: float | None


def measure_stability(values: tuple[float | None, ...]) -> StabilityResult:
    import math

    observed = [value for value in values if value is not None]
    if any(not math.isfinite(value) for value in observed):
        raise ValueError("non-finite measurement")
    signs = [0 if value == 0 else (1 if value > 0 else -1) for value in observed]
    agreement = max(signs.count(sign) for sign in set(signs)) / len(signs) if signs else None
    return StabilityResult(
        count=len(observed),
        missing_count=len(values) - len(observed),
        mean=mean(observed) if observed else None,
        standard_deviation=pstdev(observed) if len(observed) >= 2 else None,
        sign_agreement=agreement if len(observed) >= 2 else None,
    )
