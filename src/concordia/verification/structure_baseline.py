"""Independent, geometry-only baseline for structure-claim evaluation.

This module is deliberately small and conservative.  It does not score a
structure, train a model, or turn a reference label into evidence.  It asks a
separate question: how well does the fixed physical-plausibility rule perform
when used as a null classifier on explicitly labelled retrospective cases?
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from concordia.verification.structure_rules import StructureMeasurements, plausibility

STRUCTURE_BASELINE_VERSION = "structure-null-baseline-v1"


class StructureBaselineCase(BaseModel):
    """One retrospective case with an external reference label.

    ``reference_supported`` is a benchmark label only.  It is never converted
    into an evidence record for a prospective claim.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=160)
    measurements: StructureMeasurements
    reference_supported: bool


class StructureBaselineMetrics(BaseModel):
    """Confusion counts and metrics for the fixed null classifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int = Field(ge=1)
    positive_cases: int = Field(ge=1)
    negative_cases: int = Field(ge=1)
    true_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)
    balanced_accuracy: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    specificity: float = Field(ge=0, le=1)


class StructureBaselineReport(BaseModel):
    """Auditable result of the independent baseline benchmark."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_id: Literal["geometry-only-null"] = "geometry-only-null"
    version: str = STRUCTURE_BASELINE_VERSION
    case_ids: tuple[str, ...]
    metrics: StructureBaselineMetrics
    benchmark_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_label_source: Literal["external-retrospective-label"] = "external-retrospective-label"
    scientific_use_allowed: bool = False
    prospective_claim_allowed: bool = False
    limitation: str = (
        "This is a fixed physical-plausibility control, not an independent antibody "
        "structure predictor; it cannot establish binding, correctness, or causality."
    )


def _mean(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def run_structure_baseline(cases: tuple[StructureBaselineCase, ...]) -> StructureBaselineReport:
    """Evaluate the fixed geometry-only rule on retrospective labelled cases.

    The benchmark must contain both positive and negative labels so a trivial
    one-class result cannot be presented as a useful validation result.
    """

    if len(cases) < 2:
        raise ValueError("structure baseline requires at least two labelled cases")
    case_ids = tuple(case.case_id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("structure baseline case_id values must be unique")
    positive_cases = sum(case.reference_supported for case in cases)
    negative_cases = len(cases) - positive_cases
    if not positive_cases or not negative_cases:
        raise ValueError("structure baseline requires both positive and negative labels")

    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    predictions: list[dict[str, object]] = []
    for case in cases:
        predicted = plausibility(case.measurements)[0] == "supports"
        if predicted and case.reference_supported:
            counts["tp"] += 1
        elif not predicted and not case.reference_supported:
            counts["tn"] += 1
        elif predicted:
            counts["fp"] += 1
        else:
            counts["fn"] += 1
        predictions.append(
            {
                "case_id": case.case_id,
                "predicted_supported": predicted,
                "reference_supported": case.reference_supported,
            }
        )

    metrics = StructureBaselineMetrics(
        n=len(cases),
        positive_cases=positive_cases,
        negative_cases=negative_cases,
        true_positive=counts["tp"],
        true_negative=counts["tn"],
        false_positive=counts["fp"],
        false_negative=counts["fn"],
        accuracy=_mean(counts["tp"] + counts["tn"], len(cases)),
        balanced_accuracy=(
            _mean(counts["tp"], positive_cases) + _mean(counts["tn"], negative_cases)
        )
        / 2,
        precision=_mean(counts["tp"], counts["tp"] + counts["fp"]),
        recall=_mean(counts["tp"], positive_cases),
        specificity=_mean(counts["tn"], negative_cases),
    )
    digest_payload = {
        "baseline_id": "geometry-only-null",
        "version": STRUCTURE_BASELINE_VERSION,
        "cases": predictions,
        "metrics": metrics.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return StructureBaselineReport(
        case_ids=case_ids,
        metrics=metrics,
        benchmark_digest=digest,
    )


__all__ = [
    "STRUCTURE_BASELINE_VERSION",
    "StructureBaselineCase",
    "StructureBaselineMetrics",
    "StructureBaselineReport",
    "run_structure_baseline",
]
