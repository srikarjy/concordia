"""Durable campaign, candidate, measurement, and recommendation records.

This is intentionally a small SQLite-backed domain store for the first vertical
slice. The schemas and transaction boundaries are designed to migrate to the
authoritative Postgres store without changing the scientific contracts.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from concordia.campaigns.design import BinderDesignPlan, CampaignDesignRecord, stage_requests
from concordia.campaigns.redaction import redact_for_log
from concordia.campaigns.schema import (
    AssayStatus,
    Campaign,
    CampaignAccessGrant,
    CampaignAuditEvent,
    CampaignModelJob,
    CampaignModelRun,
    CampaignRound,
    CampaignStatus,
    Candidate,
    DatasetSnapshot,
    EvidenceClaim,
    EvidenceStatus,
    Measurement,
    ModelJobStatus,
    ModelRunStatus,
    Recommendation,
    RoundStatus,
    utc_now,
)
from concordia.campaigns.security import (
    CampaignAction,
    CampaignPrincipal,
    OrganizationRole,
    require_action,
)
from concordia.campaigns.study import (
    CampaignStudy,
    StudyAdmissionReport,
    StudyStatus,
    evaluate_study_admission,
    freeze_study,
)
from concordia.campaigns.validation import _is_sha256

if TYPE_CHECKING:
    from concordia.campaigns.training import ProteinTrainingExample


class CampaignNotFoundError(LookupError):
    pass


class CampaignConflictError(RuntimeError):
    pass


class CreateCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2_000)
    target_sequence: str = Field(min_length=1, max_length=100_000)
    target_construct: dict[str, Any] = Field(default_factory=dict)


class CreateCampaignResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign: Campaign
    access_token: str


class CreateAccessGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: str = Field(min_length=1, max_length=200)
    role: OrganizationRole
    lifetime_seconds: int = Field(default=86_400, ge=60, le=31_536_000)


class CreateAccessGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: str
    principal_id: str
    role: OrganizationRole
    access_token: str
    expires_at: datetime


class CreateRoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str = Field(min_length=1, max_length=200)
    assay_context: dict[str, Any] = Field(default_factory=dict)
    budget: float = Field(default=0, ge=0)
    batch_size: int = Field(default=1, ge=1, le=100_000)


class CreateStudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_digest: str = Field(min_length=64, max_length=64)
    dataset_digest: str = Field(min_length=64, max_length=64)
    selection_manifest_digest: str = Field(min_length=64, max_length=64)
    model_pin: str = Field(min_length=1, max_length=500)
    evidence_families: tuple[str, ...] = Field(min_length=2, max_length=50)
    preregistered_outcomes: tuple[str, ...] = Field(min_length=1, max_length=100)


class TransitionCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CampaignStatus


class TransitionRoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RoundStatus


class AddCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(min_length=1, max_length=100_000)
    parent_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    source: str = Field(min_length=1, max_length=200)
    construct_metadata: dict[str, Any] = Field(default_factory=dict)
    protected_positions: tuple[int, ...] = Field(default_factory=tuple, max_length=10000)


class RecordMeasurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    metric: str = Field(min_length=1, max_length=200)
    value: float | None = None
    unit: str | None = Field(default=None, max_length=80)
    method: str = Field(min_length=1, max_length=200)
    status: AssayStatus
    replicate: int = Field(default=1, ge=1)
    source_artifact_digest: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_value_for_status(self) -> RecordMeasurementRequest:
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


class ImportAssayCSVRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    csv_text: str = Field(min_length=1, max_length=2_000_000)


class CreateEvidenceClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1, max_length=200)
    claim_type: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=100)


class VerifyEvidenceClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: EvidenceStatus
    verifier: str = Field(min_length=1, max_length=200)
    independent_validation: bool = False


class CreateDesignPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_structure_digest: str = Field(min_length=64, max_length=64)
    contigs: str = Field(min_length=1, max_length=500)
    hotspot_residues: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    num_backbones: int = Field(default=8, ge=1, le=100)
    sequences_per_backbone: int = Field(default=8, ge=1, le=100)
    max_cofolds: int = Field(default=16, ge=1, le=100)
    budget_units: float = Field(default=10, gt=0, le=100_000)


class RecordModelRunRequest(BaseModel):
    """Client-facing model-run metadata; scientific eligibility is server-derived."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100_000)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    execution_mode: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    output_artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    status: ModelRunStatus = ModelRunStatus.COMPLETED
    # Retained for wire compatibility so the API can reject explicit client
    # attempts, but persistence deliberately ignores this value.
    scientific_use_allowed: bool = False


class EnqueueModelJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_run_id: str = Field(min_length=1)
    max_attempts: int = Field(default=3, ge=1, le=20)
    budget_units: float = Field(default=1.0, gt=0, le=100_000)


class ReplayExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    budget_units: float = Field(default=1.0, gt=0, le=100_000)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _assert_campaign_open(campaign: Campaign) -> None:
    if campaign.status is CampaignStatus.CLOSED:
        raise CampaignConflictError("closed campaign is read-only")


def _assert_round_writable(round_record: CampaignRound) -> None:
    if round_record.status in {RoundStatus.RESULTS_COMPLETE, RoundStatus.CLOSED}:
        raise CampaignConflictError(f"round in {round_record.status.value} status is read-only")


class CampaignStore:
    """SQLite persistence with campaign and round scope enforced at the store."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "campaigns.sqlite3"
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    campaign_json TEXT NOT NULL,
                    access_token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_rounds (
                    round_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    candidate_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_parents (
                    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                    parent_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                    PRIMARY KEY (candidate_id, parent_id)
                );
                CREATE TABLE IF NOT EXISTS measurements (
                    measurement_id TEXT PRIMARY KEY,
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                    measurement_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dataset_snapshots (
                    dataset_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    dataset_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    recommendation_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    recommendation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_claims (
                    claim_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    claim_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS design_plans (
                    plan_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_runs (
                    model_run_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    model_run_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_jobs (
                    job_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    model_run_id TEXT NOT NULL REFERENCES model_runs(model_run_id),
                    job_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_audit_events (
                    event_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_access_grants (
                    grant_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    grant_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_studies (
                    study_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    round_id TEXT NOT NULL REFERENCES campaign_rounds(round_id),
                    study_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rounds_campaign ON campaign_rounds(campaign_id);
                CREATE INDEX IF NOT EXISTS idx_candidates_round ON candidates(round_id);
                CREATE INDEX IF NOT EXISTS idx_measurements_round ON measurements(round_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_claims_round ON evidence_claims(round_id);
                CREATE INDEX IF NOT EXISTS idx_audit_events_campaign
                    ON campaign_audit_events(campaign_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_access_grants_campaign
                    ON campaign_access_grants(campaign_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_studies_campaign_round
                    ON campaign_studies(campaign_id, round_id, created_at);
                """
            )

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_campaign_with_token(self, request: CreateCampaignRequest) -> CreateCampaignResponse:
        access_token = secrets.token_urlsafe(32)
        campaign = Campaign(
            campaign_id=str(uuid.uuid4()),
            organization_id=request.organization_id,
            title=request.title,
            objective=request.objective,
            target_sequence="".join(request.target_sequence.upper().split()),
            target_construct=request.target_construct,
            status=CampaignStatus.DRAFT,
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?)",
                (
                    campaign.campaign_id,
                    campaign.organization_id,
                    campaign.model_dump_json(),
                    self._token_hash(access_token),
                    campaign.created_at.isoformat(),
                ),
            )
        return CreateCampaignResponse(campaign=campaign, access_token=access_token)

    def create_campaign(self, request: CreateCampaignRequest) -> Campaign:
        return self.create_campaign_with_token(request).campaign

    def transition_campaign(self, campaign_id: str, status: CampaignStatus) -> Campaign:
        current = self.get_campaign(campaign_id)
        allowed = {
            CampaignStatus.DRAFT: {CampaignStatus.ACTIVE, CampaignStatus.CLOSED},
            CampaignStatus.ACTIVE: {CampaignStatus.PAUSED, CampaignStatus.CLOSED},
            CampaignStatus.PAUSED: {CampaignStatus.ACTIVE, CampaignStatus.CLOSED},
            CampaignStatus.CLOSED: set(),
        }
        status = CampaignStatus(status)
        if status not in allowed[current.status]:
            raise CampaignConflictError(
                f"campaign cannot transition from {current.status.value} to {status.value}"
            )
        updated = current.model_copy(update={"status": status})
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaigns SET campaign_json = ? WHERE campaign_id = ?",
                (updated.model_dump_json(), campaign_id),
            )
        self.append_audit_event(
            campaign_id,
            actor="campaign-token",
            action="campaign.status.transitioned",
            resource_type="campaign",
            resource_id=campaign_id,
            payload={"from": current.status.value, "to": status.value},
        )
        return updated

    def authorize(self, campaign_id: str, access_token: str) -> None:
        self.authorize_principal(campaign_id, access_token)

    def authorize_principal(self, campaign_id: str, access_token: str) -> CampaignPrincipal:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT organization_id, access_token_hash FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(campaign_id)
        token_digest = self._token_hash(access_token)
        if secrets.compare_digest(row["access_token_hash"], token_digest):
            return CampaignPrincipal(
                "campaign-owner", row["organization_id"], OrganizationRole.OWNER
            )
        with self._connect() as connection:
            grant_rows = connection.execute(
                "SELECT grant_json FROM campaign_access_grants WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        for grant_row in grant_rows:
            grant = CampaignAccessGrant.model_validate_json(grant_row["grant_json"])
            if grant.revoked_at is not None:
                continue
            if grant.expires_at is not None and datetime.now(UTC) >= grant.expires_at:
                continue
            if secrets.compare_digest(grant.token_digest, token_digest):
                return CampaignPrincipal(grant.principal_id, row["organization_id"], grant.role)
        raise CampaignConflictError("campaign access denied")

    def create_access_grant(
        self,
        campaign_id: str,
        access_token: str,
        request: CreateAccessGrantRequest,
    ) -> CreateAccessGrantResponse:
        principal = self.authorize_principal(campaign_id, access_token)
        require_action(principal, CampaignAction.MANAGE_ACCESS)
        created_at = utc_now()
        expires_at = created_at + timedelta(seconds=request.lifetime_seconds)
        raw_token = secrets.token_urlsafe(32)
        grant = CampaignAccessGrant(
            grant_id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            principal_id=request.principal_id,
            role=request.role,
            token_digest=self._token_hash(raw_token),
            created_at=created_at,
            expires_at=expires_at,
            revoked_at=None,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO campaign_access_grants VALUES (?, ?, ?, ?)",
                (grant.grant_id, campaign_id, grant.model_dump_json(), created_at.isoformat()),
            )
        self.append_audit_event(
            campaign_id,
            actor=principal.principal_id,
            action="access.grant.created",
            resource_type="access_grant",
            resource_id=grant.grant_id,
            payload={"principal_id": grant.principal_id, "role": grant.role.value},
        )
        return CreateAccessGrantResponse(
            grant_id=grant.grant_id,
            principal_id=grant.principal_id,
            role=grant.role,
            access_token=raw_token,
            expires_at=expires_at,
        )

    def revoke_access_grant(self, campaign_id: str, access_token: str, grant_id: str) -> None:
        principal = self.authorize_principal(campaign_id, access_token)
        require_action(principal, CampaignAction.MANAGE_ACCESS)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT grant_json FROM campaign_access_grants "
                "WHERE grant_id = ? AND campaign_id = ?",
                (grant_id, campaign_id),
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(grant_id)
        grant = CampaignAccessGrant.model_validate_json(row["grant_json"])
        if grant.revoked_at is not None:
            return
        revoked = grant.model_copy(update={"revoked_at": utc_now()})
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaign_access_grants SET grant_json = ? WHERE grant_id = ?",
                (revoked.model_dump_json(), grant_id),
            )
        self.append_audit_event(
            campaign_id,
            actor=principal.principal_id,
            action="access.grant.revoked",
            resource_type="access_grant",
            resource_id=grant_id,
        )

    def get_campaign(self, campaign_id: str) -> Campaign:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT campaign_json FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(campaign_id)
        return Campaign.model_validate_json(row["campaign_json"])

    def append_audit_event(
        self,
        campaign_id: str,
        *,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        payload: dict[str, Any] | None = None,
    ) -> CampaignAuditEvent:
        self.get_campaign(campaign_id)
        event = CampaignAuditEvent(
            event_id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=redact_for_log(payload or {}),
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO campaign_audit_events VALUES (?, ?, ?, ?)",
                (
                    event.event_id,
                    campaign_id,
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                ),
            )
        return event

    def list_audit_events(self, campaign_id: str) -> tuple[CampaignAuditEvent, ...]:
        self.get_campaign(campaign_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM campaign_audit_events "
                "WHERE campaign_id = ? ORDER BY created_at, event_id",
                (campaign_id,),
            ).fetchall()
        return tuple(CampaignAuditEvent.model_validate_json(row["event_json"]) for row in rows)

    def create_round(self, campaign_id: str, request: CreateRoundRequest) -> CampaignRound:
        campaign = self.get_campaign(campaign_id)
        _assert_campaign_open(campaign)
        with self._connect() as connection:
            number = connection.execute(
                "SELECT COALESCE(MAX(json_extract(round_json, '$.round_number')), 0) + 1 "
                "FROM campaign_rounds WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()[0]
            round_record = CampaignRound(
                round_id=str(uuid.uuid4()),
                campaign_id=campaign.campaign_id,
                round_number=int(number),
                protocol_version=request.protocol_version,
                assay_context=request.assay_context,
                budget=request.budget,
                batch_size=request.batch_size,
                status=RoundStatus.DRAFT,
                created_at=utc_now(),
            )
            connection.execute(
                "INSERT INTO campaign_rounds VALUES (?, ?, ?, ?)",
                (
                    round_record.round_id,
                    campaign_id,
                    round_record.model_dump_json(),
                    round_record.created_at.isoformat(),
                ),
            )
        return round_record

    def transition_round(self, round_id: str, status: RoundStatus) -> CampaignRound:
        current = self._get_round(round_id)
        allowed = {
            RoundStatus.DRAFT: {RoundStatus.ACTIVE, RoundStatus.CLOSED},
            RoundStatus.ACTIVE: {
                RoundStatus.RESULTS_PARTIAL,
                RoundStatus.RESULTS_COMPLETE,
                RoundStatus.CLOSED,
            },
            RoundStatus.RESULTS_PARTIAL: {
                RoundStatus.ACTIVE,
                RoundStatus.RESULTS_COMPLETE,
                RoundStatus.CLOSED,
            },
            RoundStatus.RESULTS_COMPLETE: {RoundStatus.CLOSED},
            RoundStatus.CLOSED: set(),
        }
        status = RoundStatus(status)
        if status not in allowed[current.status]:
            raise CampaignConflictError(
                f"round cannot transition from {current.status.value} to {status.value}"
            )
        updated = current.model_copy(update={"status": status})
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaign_rounds SET round_json = ? WHERE round_id = ?",
                (updated.model_dump_json(), round_id),
            )
        self.append_audit_event(
            current.campaign_id,
            actor="campaign-token",
            action="round.status.transitioned",
            resource_type="round",
            resource_id=round_id,
            payload={"from": current.status.value, "to": status.value},
        )
        return updated

    def _get_round(self, round_id: str) -> CampaignRound:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT round_json FROM campaign_rounds WHERE round_id = ?", (round_id,)
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(round_id)
        return CampaignRound.model_validate_json(row["round_json"])

    def get_round(self, round_id: str) -> CampaignRound:
        return self._get_round(round_id)

    def list_rounds(self, campaign_id: str) -> tuple[CampaignRound, ...]:
        self.get_campaign(campaign_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT round_json FROM campaign_rounds WHERE campaign_id = ? "
                "ORDER BY json_extract(round_json, '$.round_number')",
                (campaign_id,),
            ).fetchall()
        return tuple(CampaignRound.model_validate_json(row["round_json"]) for row in rows)

    def list_candidates(self, round_id: str) -> tuple[Candidate, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT candidate_json FROM candidates WHERE round_id = ? ORDER BY candidate_id",
                (round_id,),
            ).fetchall()
        return tuple(Candidate.model_validate_json(row["candidate_json"]) for row in rows)

    def add_candidate(self, round_id: str, request: AddCandidateRequest) -> Candidate:
        round_record = self._get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        sequence = "".join(request.sequence.upper().split())
        candidate = Candidate(
            candidate_id=str(uuid.uuid4()),
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            sequence=sequence,
            sequence_hash=_sequence_hash(sequence),
            parent_ids=request.parent_ids,
            source=request.source,
            construct_metadata={
                **request.construct_metadata,
                "protected_positions": list(request.protected_positions),
            },
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if request.parent_ids:
                    placeholders = ",".join("?" for _ in request.parent_ids)
                    rows = connection.execute(
                        "SELECT candidate_id, campaign_id FROM candidates "
                        f"WHERE candidate_id IN ({placeholders})",
                        request.parent_ids,
                    ).fetchall()
                    if len(rows) != len(request.parent_ids) or any(
                        row["campaign_id"] != round_record.campaign_id for row in rows
                    ):
                        raise CampaignConflictError(
                            "candidate parents must belong to this campaign"
                        )
                connection.execute(
                    "INSERT INTO candidates VALUES (?, ?, ?, ?, ?)",
                    (
                        candidate.candidate_id,
                        candidate.campaign_id,
                        candidate.round_id,
                        candidate.model_dump_json(),
                        candidate.created_at.isoformat(),
                    ),
                )
                connection.executemany(
                    "INSERT INTO candidate_parents VALUES (?, ?)",
                    [(candidate.candidate_id, parent_id) for parent_id in request.parent_ids],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return candidate

    def record_measurement(self, round_id: str, request: RecordMeasurementRequest) -> Measurement:
        round_record = self._get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT candidate_id, campaign_id FROM candidates WHERE candidate_id = ?",
                (request.candidate_id,),
            ).fetchone()
            if row is None or row["campaign_id"] != round_record.campaign_id:
                raise CampaignConflictError("measurement candidate is outside this campaign")
        measurement = Measurement(
            measurement_id=str(uuid.uuid4()),
            round_id=round_id,
            candidate_id=request.candidate_id,
            metric=request.metric,
            value=request.value,
            unit=request.unit,
            method=request.method,
            status=request.status,
            replicate=request.replicate,
            source_artifact_digest=request.source_artifact_digest,
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO measurements VALUES (?, ?, ?, ?, ?)",
                (
                    measurement.measurement_id,
                    round_id,
                    measurement.candidate_id,
                    measurement.model_dump_json(),
                    measurement.created_at.isoformat(),
                ),
            )
        return measurement

    def record_measurements(
        self, round_id: str, requests: tuple[RecordMeasurementRequest, ...]
    ) -> tuple[Measurement, ...]:
        """Write an already-validated assay batch atomically."""
        round_record = self._get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        measurements = tuple(
            Measurement(
                measurement_id=str(uuid.uuid4()),
                round_id=round_id,
                candidate_id=request.candidate_id,
                metric=request.metric,
                value=request.value,
                unit=request.unit,
                method=request.method,
                status=request.status,
                replicate=request.replicate,
                source_artifact_digest=request.source_artifact_digest,
                created_at=utc_now(),
            )
            for request in requests
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if requests:
                    placeholders = ",".join("?" for _ in requests)
                    rows = connection.execute(
                        "SELECT candidate_id, campaign_id FROM candidates "
                        f"WHERE candidate_id IN ({placeholders})",
                        tuple(request.candidate_id for request in requests),
                    ).fetchall()
                    if len(rows) != len(set(request.candidate_id for request in requests)) or any(
                        row["campaign_id"] != round_record.campaign_id for row in rows
                    ):
                        raise CampaignConflictError(
                            "measurement candidate is outside this campaign"
                        )
                connection.executemany(
                    "INSERT INTO measurements VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            measurement.measurement_id,
                            round_id,
                            measurement.candidate_id,
                            measurement.model_dump_json(),
                            measurement.created_at.isoformat(),
                        )
                        for measurement in measurements
                    ],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return measurements

    def list_measurements(self, round_id: str) -> tuple[Measurement, ...]:
        self._get_round(round_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT measurement_json FROM measurements WHERE round_id = ? "
                "ORDER BY measurement_id",
                (round_id,),
            ).fetchall()
        return tuple(Measurement.model_validate_json(row["measurement_json"]) for row in rows)

    def freeze_dataset(self, round_id: str, transformation_policy: str) -> DatasetSnapshot:
        round_record = self._get_round(round_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT measurement_id, measurement_json FROM measurements "
                "WHERE round_id = ? ORDER BY measurement_id",
                (round_id,),
            ).fetchall()
            measurement_ids = tuple(row["measurement_id"] for row in rows)
            dataset_digest = hashlib.sha256(
                _json(
                    {
                        "measurement_ids": measurement_ids,
                        "measurements": [json.loads(row["measurement_json"]) for row in rows],
                        "transformation_policy": transformation_policy,
                    }
                ).encode()
            ).hexdigest()
            dataset = DatasetSnapshot(
                dataset_id=str(uuid.uuid4()),
                campaign_id=round_record.campaign_id,
                round_id=round_id,
                measurement_ids=measurement_ids,
                transformation_policy=transformation_policy,
                dataset_digest=dataset_digest,
                row_count=len(rows),
                created_at=utc_now(),
            )
            connection.execute(
                "INSERT INTO dataset_snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    dataset.dataset_id,
                    dataset.campaign_id,
                    round_id,
                    dataset.model_dump_json(),
                    dataset.created_at.isoformat(),
                ),
            )
        return dataset

    def get_dataset_snapshot(self, dataset_id: str) -> DatasetSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT dataset_json FROM dataset_snapshots WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(dataset_id)
        return DatasetSnapshot.model_validate_json(row["dataset_json"])

    def list_datasets(self, round_id: str) -> tuple[DatasetSnapshot, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT dataset_json FROM dataset_snapshots WHERE round_id = ? ORDER BY dataset_id",
                (round_id,),
            ).fetchall()
        return tuple(DatasetSnapshot.model_validate_json(row["dataset_json"]) for row in rows)

    def create_study(self, round_id: str, request: CreateStudyRequest) -> CampaignStudy:
        round_record = self._get_round(round_id)
        campaign = self.get_campaign(round_record.campaign_id)
        _assert_campaign_open(campaign)
        _assert_round_writable(round_record)
        if not any(
            dataset.dataset_digest == request.dataset_digest
            for dataset in self.list_datasets(round_id)
        ):
            raise CampaignConflictError("study dataset digest is not a frozen round dataset")
        study = CampaignStudy(
            study_id=str(uuid.uuid4()),
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            protocol_digest=request.protocol_digest,
            dataset_digest=request.dataset_digest,
            selection_manifest_digest=request.selection_manifest_digest,
            model_pin=request.model_pin,
            evidence_families=request.evidence_families,
            preregistered_outcomes=request.preregistered_outcomes,
            status=StudyStatus.DRAFT,
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO campaign_studies VALUES (?, ?, ?, ?, ?)",
                (
                    study.study_id,
                    study.campaign_id,
                    study.round_id,
                    study.model_dump_json(),
                    study.created_at.isoformat(),
                ),
            )
        self.append_audit_event(
            study.campaign_id,
            actor="campaign-token",
            action="study.created",
            resource_type="study",
            resource_id=study.study_id,
            payload={"round_id": round_id, "dataset_digest": study.dataset_digest},
        )
        return study

    def get_study(self, study_id: str) -> CampaignStudy:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT study_json FROM campaign_studies WHERE study_id = ?", (study_id,)
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(study_id)
        return CampaignStudy.model_validate_json(row["study_json"])

    def list_studies(self, round_id: str) -> tuple[CampaignStudy, ...]:
        self._get_round(round_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT study_json FROM campaign_studies WHERE round_id = ? ORDER BY study_id",
                (round_id,),
            ).fetchall()
        return tuple(CampaignStudy.model_validate_json(row["study_json"]) for row in rows)

    def freeze_study_record(self, study_id: str) -> CampaignStudy:
        study = self.get_study(study_id)
        _assert_campaign_open(self.get_campaign(study.campaign_id))
        frozen = freeze_study(study)
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaign_studies SET study_json = ? WHERE study_id = ?",
                (frozen.model_dump_json(), study_id),
            )
        self.append_audit_event(
            study.campaign_id,
            actor="campaign-token",
            action="study.frozen",
            resource_type="study",
            resource_id=study_id,
            payload={"dataset_digest": study.dataset_digest},
        )
        return frozen

    def admit_study(self, study_id: str) -> tuple[CampaignStudy, StudyAdmissionReport]:
        study = self.get_study(study_id)
        datasets = self.list_datasets(study.round_id)
        dataset_ids = {dataset.dataset_id for dataset in datasets}
        dataset_exists = any(dataset.dataset_digest == study.dataset_digest for dataset in datasets)
        audit_events = self.list_audit_events(study.campaign_id)
        benchmark_recorded = any(
            event.action == "benchmark.completed"
            and event.resource_id in dataset_ids
            and _is_sha256(str(event.payload.get("benchmark_digest", "")))
            and _is_sha256(str(event.payload.get("artifact_digest", "")))
            for event in audit_events
        )
        model_pin_observed = any(
            run.model == study.model_pin
            or run.model_version == study.model_pin
            or f"{run.model}@{run.model_version}" == study.model_pin
            for run in self.list_model_runs(study.round_id)
        )
        report = evaluate_study_admission(
            study,
            dataset_exists=dataset_exists,
            benchmark_recorded=bool(benchmark_recorded),
            model_pin_observed=model_pin_observed,
        )
        reasons = tuple(reason for _, passed, reason in report.checks if not passed)
        updated = study.model_copy(update={"status": report.status, "admission_reasons": reasons})
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaign_studies SET study_json = ? WHERE study_id = ?",
                (updated.model_dump_json(), study_id),
            )
        self.append_audit_event(
            study.campaign_id,
            actor="campaign-token",
            action="study.admission.evaluated",
            resource_type="study",
            resource_id=study_id,
            payload={"status": report.status.value, "passed": report.passed},
        )
        return updated, report

    def create_design_plan(self, round_id: str, plan: BinderDesignPlan) -> CampaignDesignRecord:
        round_record = self._get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        record = CampaignDesignRecord(
            plan=plan,
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            stages=stage_requests(plan),
            created_at=utc_now().isoformat(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO design_plans VALUES (?, ?, ?, ?, ?)",
                (
                    plan.plan_id,
                    record.campaign_id,
                    round_id,
                    record.model_dump_json(),
                    record.created_at,
                ),
            )
        return record

    def get_design_plan(self, plan_id: str) -> CampaignDesignRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan_json FROM design_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(plan_id)
        return CampaignDesignRecord.model_validate_json(row["plan_json"])

    def get_training_examples(
        self, dataset_id: str, *, metric: str | None = None
    ) -> tuple[ProteinTrainingExample, ...]:
        """Resolve only measured, numeric labels from an immutable snapshot."""
        from concordia.campaigns.training import ProteinTrainingExample

        snapshot = self.get_dataset_snapshot(dataset_id)
        with self._connect() as connection:
            placeholders = ",".join("?" for _ in snapshot.measurement_ids)
            if not placeholders:
                return ()
            rows = connection.execute(
                "SELECT m.measurement_json, c.candidate_json "
                "FROM measurements AS m JOIN candidates AS c ON c.candidate_id = m.candidate_id "
                f"WHERE m.measurement_id IN ({placeholders}) ORDER BY m.measurement_id",
                snapshot.measurement_ids,
            ).fetchall()
        grouped: dict[tuple[str, str], tuple[str, list[float]]] = {}
        for row in rows:
            measurement = Measurement.model_validate_json(row["measurement_json"])
            candidate = Candidate.model_validate_json(row["candidate_json"])
            if metric is not None and measurement.metric != metric:
                continue
            if measurement.status is not AssayStatus.MEASURED or measurement.value is None:
                continue
            key = (candidate.candidate_id, measurement.metric)
            if key not in grouped:
                grouped[key] = (candidate.sequence, [])
            grouped[key][1].append(measurement.value)
        return tuple(
            ProteinTrainingExample(
                candidate_id=candidate_id,
                sequence=sequence,
                value=sum(values) / len(values),
            )
            for (candidate_id, _), (sequence, values) in sorted(grouped.items())
        )

    def create_recommendation(
        self,
        round_id: str,
        candidate_ids: tuple[str, ...],
        *,
        policy: str,
        evidence_snapshot: tuple[str, ...],
        rationale: dict[str, Any],
    ) -> Recommendation:
        round_record = self._get_round(round_id)
        with self._connect() as connection:
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                rows = connection.execute(
                    "SELECT candidate_id FROM candidates WHERE round_id = ? "
                    f"AND candidate_id IN ({placeholders})",
                    (round_id, *candidate_ids),
                ).fetchall()
                if len(rows) != len(set(candidate_ids)):
                    raise CampaignConflictError(
                        "recommendation candidates must belong to the round"
                    )
        recommendation = Recommendation(
            recommendation_id=str(uuid.uuid4()),
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            candidate_ids=candidate_ids,
            policy=policy,
            evidence_snapshot=evidence_snapshot,
            rationale=rationale,
            status="draft",
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO recommendations VALUES (?, ?, ?, ?, ?)",
                (
                    recommendation.recommendation_id,
                    recommendation.campaign_id,
                    round_id,
                    recommendation.model_dump_json(),
                    recommendation.created_at.isoformat(),
                ),
            )
        return recommendation

    def record_model_run(self, round_id: str, request: RecordModelRunRequest) -> CampaignModelRun:
        round_record = self._get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        with self._connect() as connection:
            if request.candidate_ids:
                placeholders = ",".join("?" for _ in request.candidate_ids)
                rows = connection.execute(
                    "SELECT candidate_id FROM candidates WHERE round_id = ? "
                    f"AND candidate_id IN ({placeholders})",
                    (round_id, *request.candidate_ids),
                ).fetchall()
                if len(rows) != len(set(request.candidate_ids)):
                    raise CampaignConflictError("model-run candidates must belong to the round")
        model_run = CampaignModelRun(
            model_run_id=str(uuid.uuid4()),
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            candidate_ids=request.candidate_ids,
            provider=request.provider,
            model=request.model,
            model_version=request.model_version,
            execution_mode=request.execution_mode,
            parameters=request.parameters,
            input_artifact_digests=request.input_artifact_digests,
            output_artifact_digests=request.output_artifact_digests,
            status=request.status,
            # Scientific eligibility is derived by validation gates, never by a
            # caller-provided model-run field. Keep this invariant at the
            # persistence boundary as well as in the HTTP API.
            scientific_use_allowed=False,
            created_at=utc_now(),
            input_digest=hashlib.sha256(_json(request.input_artifact_digests).encode()).hexdigest(),
            parameter_digest=hashlib.sha256(_json(request.parameters).encode()).hexdigest(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_runs VALUES (?, ?, ?, ?, ?)",
                (
                    model_run.model_run_id,
                    model_run.campaign_id,
                    round_id,
                    model_run.model_dump_json(),
                    model_run.created_at.isoformat(),
                ),
            )
        return model_run

    def create_evidence_claim(
        self, round_id: str, request: CreateEvidenceClaimRequest
    ) -> EvidenceClaim:
        round_record = self._get_round(round_id)
        claim = EvidenceClaim(
            claim_id=str(uuid.uuid4()),
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            subject_id=request.subject_id,
            claim_type=request.claim_type,
            statement=request.statement,
            evidence_artifact_digests=request.evidence_artifact_digests,
            verification_status=EvidenceStatus.UNVERIFIED,
            verifier=None,
            scientific_use_allowed=False,
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO evidence_claims VALUES (?, ?, ?, ?, ?)",
                (
                    claim.claim_id,
                    claim.campaign_id,
                    round_id,
                    claim.model_dump_json(),
                    claim.created_at.isoformat(),
                ),
            )
        return claim

    def get_evidence_claim(self, claim_id: str) -> EvidenceClaim:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT claim_json FROM evidence_claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(claim_id)
        return EvidenceClaim.model_validate_json(row["claim_json"])

    def verify_evidence_claim(
        self,
        claim_id: str,
        *,
        status: EvidenceStatus,
        verifier: str,
        independent_validation: bool = False,
    ) -> EvidenceClaim:
        if not verifier:
            raise ValueError("verifier is required")
        if status is EvidenceStatus.SUPPORTED and not independent_validation:
            raise CampaignConflictError("supported claims require independent validation evidence")
        current = self.get_evidence_claim(claim_id)
        if current.verification_status in {EvidenceStatus.SUPPORTED, EvidenceStatus.REJECTED}:
            raise CampaignConflictError("terminal evidence claim cannot be re-verified")
        verified = current.model_copy(
            update={
                "verification_status": status,
                "verifier": verifier,
                "scientific_use_allowed": status is EvidenceStatus.SUPPORTED
                and independent_validation,
            }
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE evidence_claims SET claim_json = ? WHERE claim_id = ?",
                (verified.model_dump_json(), claim_id),
            )
        return verified

    def get_model_run(self, model_run_id: str) -> CampaignModelRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT model_run_json FROM model_runs WHERE model_run_id = ?",
                (model_run_id,),
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(model_run_id)
        return CampaignModelRun.model_validate_json(row["model_run_json"])

    def clone_model_run_for_replay(self, model_run_id: str) -> CampaignModelRun:
        source = self.get_model_run(model_run_id)
        round_record = self._get_round(source.round_id)
        _assert_campaign_open(self.get_campaign(source.campaign_id))
        _assert_round_writable(round_record)
        replay = source.model_copy(
            update={
                "model_run_id": str(uuid.uuid4()),
                "status": ModelRunStatus.QUEUED,
                "output_artifact_digests": (),
                "scientific_use_allowed": False,
                "created_at": utc_now(),
            }
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_runs VALUES (?, ?, ?, ?, ?)",
                (
                    replay.model_run_id,
                    replay.campaign_id,
                    replay.round_id,
                    replay.model_dump_json(),
                    replay.created_at.isoformat(),
                ),
            )
        self.append_audit_event(
            replay.campaign_id,
            actor="campaign-token",
            action="model_run.replay.execute.queued",
            resource_type="model_run",
            resource_id=replay.model_run_id,
            payload={"source_model_run_id": source.model_run_id},
        )
        return replay

    def list_model_runs(self, round_id: str) -> tuple[CampaignModelRun, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT model_run_json FROM model_runs WHERE round_id = ? ORDER BY model_run_id",
                (round_id,),
            ).fetchall()
        return tuple(CampaignModelRun.model_validate_json(row["model_run_json"]) for row in rows)

    def list_recommendations(self, round_id: str) -> tuple[Recommendation, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT recommendation_json FROM recommendations WHERE round_id = ? "
                "ORDER BY recommendation_id",
                (round_id,),
            ).fetchall()
        return tuple(Recommendation.model_validate_json(row["recommendation_json"]) for row in rows)

    def get_recommendation(self, recommendation_id: str) -> Recommendation:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT recommendation_json FROM recommendations WHERE recommendation_id = ?",
                (recommendation_id,),
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(recommendation_id)
        return Recommendation.model_validate_json(row["recommendation_json"])

    def get_candidate(self, candidate_id: str) -> Candidate:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT candidate_json FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(candidate_id)
        return Candidate.model_validate_json(row["candidate_json"])

    def list_evidence_claims(self, round_id: str) -> tuple[EvidenceClaim, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT claim_json FROM evidence_claims WHERE round_id = ? ORDER BY claim_id",
                (round_id,),
            ).fetchall()
        return tuple(EvidenceClaim.model_validate_json(row["claim_json"]) for row in rows)

    def complete_model_run(
        self,
        model_run_id: str,
        *,
        output_artifact_digests: tuple[str, ...],
        status: ModelRunStatus = ModelRunStatus.COMPLETED,
    ) -> CampaignModelRun:
        current = self.get_model_run(model_run_id)
        completed = current.model_copy(
            update={"output_artifact_digests": output_artifact_digests, "status": status}
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_runs SET model_run_json = ? WHERE model_run_id = ?",
                (completed.model_dump_json(), model_run_id),
            )
        return completed

    def enqueue_model_job(
        self, campaign_id: str, request: EnqueueModelJobRequest
    ) -> CampaignModelJob:
        self.get_campaign(campaign_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT model_runs.campaign_id, model_runs.round_id, "
                "json_extract(campaign_rounds.round_json, '$.budget') AS budget "
                "FROM model_runs JOIN campaign_rounds "
                "ON campaign_rounds.round_id = model_runs.round_id "
                "WHERE model_runs.model_run_id = ?",
                (request.model_run_id,),
            ).fetchone()
        if row is None or row["campaign_id"] != campaign_id:
            raise CampaignConflictError("model run does not belong to campaign")
        _assert_campaign_open(self.get_campaign(campaign_id))
        _assert_round_writable(self._get_round(row["round_id"]))
        if row["budget"] and request.budget_units > float(row["budget"]):
            raise CampaignConflictError("model job budget exceeds round budget")
        now = utc_now()
        job = CampaignModelJob(
            job_id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            round_id=row["round_id"],
            model_run_id=request.model_run_id,
            status=ModelJobStatus.QUEUED,
            attempt=0,
            max_attempts=request.max_attempts,
            lease_owner=None,
            lease_expires_at=None,
            provider_request_id=None,
            cancel_requested=False,
            created_at=now,
            budget_units=request.budget_units,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_jobs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.campaign_id,
                    job.round_id,
                    job.model_run_id,
                    job.model_dump_json(),
                    now.isoformat(),
                ),
            )
        self.append_audit_event(
            campaign_id,
            actor="system",
            action="model_job.queued",
            resource_type="model_job",
            resource_id=job.job_id,
            payload={"round_id": job.round_id, "model_run_id": job.model_run_id},
        )
        return job

    def get_model_job(self, job_id: str) -> CampaignModelJob:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT job_json FROM model_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise CampaignNotFoundError(job_id)
        return CampaignModelJob.model_validate_json(row["job_json"])

    def list_model_jobs(self, campaign_id: str) -> tuple[CampaignModelJob, ...]:
        self.get_campaign(campaign_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_json FROM model_jobs WHERE campaign_id = ? ORDER BY job_id",
                (campaign_id,),
            ).fetchall()
        return tuple(CampaignModelJob.model_validate_json(row["job_json"]) for row in rows)

    def claim_model_job(
        self,
        owner: str,
        *,
        lease_seconds: float = 60,
        now: datetime | None = None,
        job_id: str | None = None,
    ) -> CampaignModelJob | None:
        if not owner or lease_seconds <= 0:
            raise ValueError("valid lease owner and duration are required")
        claimed_at = now or datetime.now(UTC)
        expiry = claimed_at + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            params: list[object] = [claimed_at.isoformat()]
            job_filter = ""
            if job_id is not None:
                job_filter = "AND job_id = ?"
                params.append(job_id)
            row = connection.execute(
                "SELECT * FROM model_jobs "
                "WHERE json_extract(job_json, '$.cancel_requested') = 0 "
                "AND json_extract(job_json, '$.attempt') < "
                "json_extract(job_json, '$.max_attempts') AND "
                "(json_extract(job_json, '$.status') = 'queued' OR "
                "(json_extract(job_json, '$.status') = 'leased' AND "
                "json_extract(job_json, '$.lease_expires_at') <= ?)) "
                f"{job_filter} ORDER BY created_at, job_id LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            current = CampaignModelJob.model_validate_json(row["job_json"])
            claimed = current.model_copy(
                update={
                    "status": ModelJobStatus.LEASED,
                    "attempt": current.attempt + 1,
                    "lease_owner": owner,
                    "lease_expires_at": expiry,
                }
            )
            connection.execute(
                "UPDATE model_jobs SET job_json = ? WHERE job_id = ?",
                (claimed.model_dump_json(), claimed.job_id),
            )
            connection.commit()
        return claimed

    def mark_model_job_submitted(
        self, job_id: str, owner: str, provider_request_id: str
    ) -> CampaignModelJob:
        current = self.get_model_job(job_id)
        if current.status is not ModelJobStatus.LEASED or current.lease_owner != owner:
            raise CampaignConflictError("worker does not own model job lease")
        submitted = current.model_copy(update={"provider_request_id": provider_request_id})
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_jobs SET job_json = ? WHERE job_id = ?",
                (submitted.model_dump_json(), job_id),
            )
        return submitted

    def finish_model_job(self, job_id: str, owner: str, status: ModelJobStatus) -> CampaignModelJob:
        status = ModelJobStatus(status)
        if status not in {ModelJobStatus.SUCCEEDED, ModelJobStatus.FAILED}:
            raise ValueError("model jobs can only finish as succeeded or failed")
        current = self.get_model_job(job_id)
        if current.status is not ModelJobStatus.LEASED or current.lease_owner != owner:
            raise CampaignConflictError("worker does not own model job lease")
        finished = current.model_copy(
            update={"status": status, "lease_owner": None, "lease_expires_at": None}
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_jobs SET job_json = ? WHERE job_id = ?",
                (finished.model_dump_json(), job_id),
            )
        self.append_audit_event(
            current.campaign_id,
            actor=owner,
            action="model_job.finished",
            resource_type="model_job",
            resource_id=job_id,
            payload={"status": status.value, "attempt": finished.attempt},
        )
        return finished

    def retry_model_job(self, job_id: str, owner: str) -> CampaignModelJob:
        current = self.get_model_job(job_id)
        if current.status is not ModelJobStatus.LEASED or current.lease_owner != owner:
            raise CampaignConflictError("worker does not own model job lease")
        if current.attempt >= current.max_attempts:
            return self.finish_model_job(job_id, owner, ModelJobStatus.FAILED)
        queued = current.model_copy(
            update={"status": ModelJobStatus.QUEUED, "lease_owner": None, "lease_expires_at": None}
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_jobs SET job_json = ? WHERE job_id = ?",
                (queued.model_dump_json(), job_id),
            )
        return queued

    def cancel_model_job(self, job_id: str) -> CampaignModelJob:
        current = self.get_model_job(job_id)
        if current.status in {ModelJobStatus.SUCCEEDED, ModelJobStatus.FAILED}:
            raise CampaignConflictError("model job is already terminal")
        cancelled = current.model_copy(
            update={
                "status": ModelJobStatus.CANCELLED,
                "cancel_requested": True,
                "lease_owner": None,
                "lease_expires_at": None,
            }
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_jobs SET job_json = ? WHERE job_id = ?",
                (cancelled.model_dump_json(), job_id),
            )
        self.append_audit_event(
            current.campaign_id,
            actor="campaign-token",
            action="model_job.cancelled",
            resource_type="model_job",
            resource_id=job_id,
            payload={"attempt": cancelled.attempt},
        )
        return cancelled
