"""Typed contracts for the campaign and experiment-learning backbone."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from concordia.campaigns.security import OrganizationRole


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class RoundStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RESULTS_PARTIAL = "results_partial"
    RESULTS_COMPLETE = "results_complete"
    CLOSED = "closed"


class AssayStatus(StrEnum):
    PLANNED = "planned"
    MEASURED = "measured"
    FAILED_EXPRESSION = "failed_expression"
    INVALID = "invalid"
    BELOW_DETECTION = "below_detection"
    ABOVE_DETECTION = "above_detection"


class ModelRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelJobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceStatus(StrEnum):
    UNVERIFIED = "unverified"
    INSUFFICIENT = "insufficient"
    SUPPORTED = "supported"
    REJECTED = "rejected"


class Campaign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    campaign_id: str
    organization_id: str
    title: str
    objective: str
    target_sequence: str
    target_construct: dict[str, Any]
    status: CampaignStatus
    created_at: datetime


class CampaignRound(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    round_id: str
    campaign_id: str
    round_number: int = Field(ge=1)
    protocol_version: str
    assay_context: dict[str, Any]
    budget: float = Field(ge=0)
    batch_size: int = Field(ge=1, le=100_000)
    status: RoundStatus
    created_at: datetime


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    candidate_id: str
    campaign_id: str
    round_id: str
    sequence: str
    sequence_hash: str
    parent_ids: tuple[str, ...]
    source: str
    construct_metadata: dict[str, Any]
    created_at: datetime

    @field_validator("sequence")
    @classmethod
    def normalize_sequence(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        if not normalized or any(residue not in "ARNDCQEGHILKMFPSTWYVX" for residue in normalized):
            raise ValueError("candidate sequence contains invalid protein residues")
        return normalized


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    measurement_id: str
    round_id: str
    candidate_id: str
    metric: str
    value: float | None
    unit: str | None
    method: str
    status: AssayStatus
    replicate: int = Field(ge=1)
    source_artifact_digest: str | None
    created_at: datetime

    @model_validator(mode="after")
    def validate_value_for_status(self) -> Measurement:
        if (
            self.status
            in {
                AssayStatus.MEASURED,
                AssayStatus.BELOW_DETECTION,
                AssayStatus.ABOVE_DETECTION,
            }
            and self.value is None
        ):
            raise ValueError(f"value is required for {self.status.value}")
        return self


class DatasetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    dataset_id: str
    campaign_id: str
    round_id: str
    measurement_ids: tuple[str, ...]
    transformation_policy: str
    dataset_digest: str = Field(min_length=64, max_length=64)
    row_count: int = Field(ge=0)
    created_at: datetime


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    recommendation_id: str
    campaign_id: str
    round_id: str
    candidate_ids: tuple[str, ...]
    policy: str
    evidence_snapshot: tuple[str, ...]
    rationale: dict[str, Any]
    status: str
    created_at: datetime


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    claim_id: str
    campaign_id: str
    round_id: str
    subject_id: str
    claim_type: str
    statement: str
    evidence_artifact_digests: tuple[str, ...]
    verification_status: EvidenceStatus
    verifier: str | None
    scientific_use_allowed: bool = False
    created_at: datetime


class CampaignAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    event_id: str
    campaign_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    payload: dict[str, Any]
    created_at: datetime


class CampaignAccessGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    grant_id: str
    campaign_id: str
    principal_id: str
    role: OrganizationRole
    token_digest: str = Field(min_length=64, max_length=64)
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class CampaignModelRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    model_run_id: str
    campaign_id: str
    round_id: str
    candidate_ids: tuple[str, ...]
    provider: str
    model: str
    model_version: str
    execution_mode: str
    parameters: dict[str, Any]
    input_artifact_digests: tuple[str, ...]
    output_artifact_digests: tuple[str, ...]
    status: ModelRunStatus
    scientific_use_allowed: bool
    created_at: datetime
    input_digest: str = ""
    parameter_digest: str = ""


class CampaignModelJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    job_id: str
    campaign_id: str
    round_id: str
    model_run_id: str
    status: ModelJobStatus
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    lease_owner: str | None
    lease_expires_at: datetime | None
    provider_request_id: str | None
    cancel_requested: bool
    created_at: datetime
    budget_units: float = Field(default=1.0, gt=0, le=100_000)


def utc_now() -> datetime:
    return datetime.now(UTC)
