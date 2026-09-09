"""Versioned contracts for durable Concordia runs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

SHA256_PATTERN = r"^[0-9a-f]{64}$"
Sha256Digest = Annotated[str, Field(pattern=SHA256_PATTERN)]


class RunStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    INGESTING = "INGESTING"
    GRAPH_READY = "GRAPH_READY"
    PLANNING = "PLANNING"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    CLAIM_VALIDATION = "CLAIM_VALIDATION"
    BACKTRACKING = "BACKTRACKING"
    EVALUATING = "EVALUATING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    FAILED_POLICY = "FAILED_POLICY"
    FAILED_TOOL = "FAILED_TOOL"
    FAILED_MODEL = "FAILED_MODEL"
    FAILED_SCHEMA = "FAILED_SCHEMA"
    FAILED_ARTIFACT = "FAILED_ARTIFACT"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class RunCommand(StrEnum):
    CREATE = "CREATE"
    REPLAY = "REPLAY"
    CANCEL = "CANCEL"


class GenomicFixtureTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_artifact_id: Sha256Digest
    scan_position: int = Field(ge=0)
    execution_mode: str = Field(default="recorded_fixture", pattern=r"^recorded_fixture$")
    max_infrastructure_attempts: int = Field(default=3, ge=1, le=10)


class RunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    run_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    protocol_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    input_artifact_ids: tuple[Sha256Digest, ...] = Field(min_length=1)
    task: GenomicFixtureTask


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: Sha256Digest
    media_type: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    schema_version: int = Field(ge=1)
    producing_event: str = Field(min_length=1)
    producing_tool: str = Field(min_length=1)
    scientific_use_allowed: bool


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    sequence_number: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    spec: RunSpec
    current_status: RunStatus
    created_at: datetime
    last_sequence_number: int = Field(ge=1)
    terminal_reason: str | None = None


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunRecord
    event_count: int = Field(ge=1)


class EventPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[RunEvent, ...]
    next_cursor: int | None = None
