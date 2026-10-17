"""Frozen campaign study records and fail-closed admission checks."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StudyStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    ADMITTED = "admitted"
    BLOCKED = "blocked"


class CampaignStudy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    study_id: str
    campaign_id: str
    round_id: str
    protocol_digest: str = Field(min_length=64, max_length=64)
    dataset_digest: str = Field(min_length=64, max_length=64)
    selection_manifest_digest: str = Field(min_length=64, max_length=64)
    model_pin: str = Field(min_length=1, max_length=500)
    evidence_families: tuple[str, ...] = Field(min_length=2, max_length=50)
    preregistered_outcomes: tuple[str, ...] = Field(min_length=1, max_length=100)
    status: StudyStatus
    admission_reasons: tuple[str, ...] = ()
    scientific_use_allowed: bool = False
    created_at: datetime


class StudyAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: str
    checks: tuple[tuple[str, bool, str], ...]
    status: StudyStatus
    scientific_use_allowed: bool = False

    @property
    def passed(self) -> bool:
        return all(passed for _, passed, _ in self.checks)


def freeze_study(study: CampaignStudy) -> CampaignStudy:
    if study.status is not StudyStatus.DRAFT:
        raise ValueError("only a draft study can be frozen")
    return study.model_copy(update={"status": StudyStatus.FROZEN, "admission_reasons": ()})


def evaluate_study_admission(
    study: CampaignStudy,
    *,
    dataset_exists: bool,
    benchmark_recorded: bool,
    model_pin_observed: bool,
) -> StudyAdmissionReport:
    """Evaluate readiness without promoting the study to scientific evidence."""
    checks = (
        (
            "frozen_protocol",
            study.status is StudyStatus.FROZEN,
            "study protocol must be frozen before admission",
        ),
        (
            "protocol_digest",
            _is_sha256(study.protocol_digest),
            "protocol identity is canonical",
        ),
        (
            "dataset_digest",
            _is_sha256(study.dataset_digest) and dataset_exists,
            "declared dataset must exist and have a canonical digest",
        ),
        (
            "selection_manifest_digest",
            _is_sha256(study.selection_manifest_digest),
            "selection manifest identity is canonical",
        ),
        (
            "model_pin",
            bool(study.model_pin.strip()) and model_pin_observed,
            "declared model pin must be observed in the campaign lineage",
        ),
        (
            "evidence_families",
            len(set(study.evidence_families)) >= 2,
            "at least two distinct evidence families are required",
        ),
        (
            "retrospective_benchmark",
            benchmark_recorded,
            "a retrospective benchmark must be recorded before admission",
        ),
    )
    status = StudyStatus.ADMITTED if all(passed for _, passed, _ in checks) else StudyStatus.BLOCKED
    return StudyAdmissionReport(
        study_id=study.study_id,
        checks=checks,
        status=status,
    )


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return hashlib.sha256(value.encode()).digest() is not None


__all__ = [
    "CampaignStudy",
    "StudyAdmissionReport",
    "StudyStatus",
    "evaluate_study_admission",
    "freeze_study",
]
