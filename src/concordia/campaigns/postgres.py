"""Postgres schema contract for the campaign domain.

The first vertical slice uses SQLite locally. These statements keep the durable
Postgres shape explicit and portable so a repository adapter can be introduced
without changing campaign payloads or lineage semantics.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

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
from concordia.campaigns.service import (
    AddCandidateRequest,
    CampaignConflictError,
    CampaignNotFoundError,
    CreateAccessGrantRequest,
    CreateAccessGrantResponse,
    CreateCampaignRequest,
    CreateCampaignResponse,
    CreateEvidenceClaimRequest,
    CreateRoundRequest,
    CreateStudyRequest,
    EnqueueModelJobRequest,
    RecordMeasurementRequest,
    RecordModelRunRequest,
    _assert_campaign_open,
    _assert_round_writable,
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
    from psycopg import Connection

    from concordia.campaigns.training import ProteinTrainingExample

CAMPAIGN_SCHEMA_VERSION = 1

CAMPAIGN_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS concordia_campaign_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_campaigns (
        campaign_id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        campaign_json JSONB NOT NULL,
        access_token_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_campaign_rounds (
        round_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_candidates (
        candidate_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        sequence_hash TEXT NOT NULL,
        candidate_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_candidate_parents (
        candidate_id TEXT NOT NULL REFERENCES concordia_candidates(candidate_id),
        parent_id TEXT NOT NULL REFERENCES concordia_candidates(candidate_id),
        PRIMARY KEY (candidate_id, parent_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_measurements (
        measurement_id TEXT PRIMARY KEY,
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        candidate_id TEXT NOT NULL REFERENCES concordia_candidates(candidate_id),
        measurement_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_dataset_snapshots (
        dataset_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        dataset_digest TEXT NOT NULL,
        dataset_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_recommendations (
        recommendation_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        recommendation_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_model_runs (
        model_run_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        model_run_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_evidence_claims (
        claim_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        verification_status TEXT NOT NULL,
        claim_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_design_plans (
        plan_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        plan_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_model_jobs (
        job_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        model_run_id TEXT NOT NULL REFERENCES concordia_model_runs(model_run_id),
        status TEXT NOT NULL,
        lease_owner TEXT,
        lease_expires_at TIMESTAMPTZ,
        job_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_campaign_audit_events (
        event_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        event_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_campaign_access_grants (
        grant_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        grant_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concordia_campaign_studies (
        study_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES concordia_campaigns(campaign_id),
        round_id TEXT NOT NULL REFERENCES concordia_campaign_rounds(round_id),
        study_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS concordia_rounds_campaign_idx "
    "ON concordia_campaign_rounds(campaign_id)",
    "CREATE INDEX IF NOT EXISTS concordia_candidates_round_idx ON concordia_candidates(round_id)",
    "CREATE INDEX IF NOT EXISTS concordia_measurements_round_idx "
    "ON concordia_measurements(round_id)",
    "CREATE INDEX IF NOT EXISTS concordia_model_jobs_claim_idx "
    "ON concordia_model_jobs(status, lease_expires_at, created_at)",
    "CREATE INDEX IF NOT EXISTS concordia_audit_events_campaign_idx "
    "ON concordia_campaign_audit_events(campaign_id, created_at)",
    "CREATE INDEX IF NOT EXISTS concordia_access_grants_campaign_idx "
    "ON concordia_campaign_access_grants(campaign_id, created_at)",
    "CREATE INDEX IF NOT EXISTS concordia_studies_campaign_round_idx "
    "ON concordia_campaign_studies(campaign_id, round_id, created_at)",
)


def migrate_campaign_schema(connection: Any) -> None:
    """Apply the idempotent campaign schema and record its applied revision."""
    with connection.cursor() as cursor:
        for statement in CAMPAIGN_SCHEMA_STATEMENTS:
            cursor.execute(statement)
        cursor.execute(
            "INSERT INTO concordia_campaign_schema_migrations (version) VALUES (%s) "
            "ON CONFLICT (version) DO NOTHING",
            (CAMPAIGN_SCHEMA_VERSION,),
        )
    connection.commit()


def schema_statements() -> Iterable[str]:
    """Expose a read-only iterable for migration tooling and inspection."""
    return CAMPAIGN_SCHEMA_STATEMENTS


def _json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class PostgresCampaignStore:
    """Authoritative Postgres implementation of the campaign store contract."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._migrate()

    def _connect(self) -> Connection[Any]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - optional dependency boundary
            raise RuntimeError(
                "Postgres campaign persistence requires the postgres extra"
            ) from error
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _migrate(self) -> None:
        with self._connect() as connection:
            migrate_campaign_schema(connection)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _model(row: dict[str, Any], key: str, model: Any) -> Any:
        return model.model_validate_json(_json_text(row[key]))

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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_campaigns "
                "(campaign_id, organization_id, campaign_json, access_token_hash, created_at) "
                "VALUES (%s, %s, %s::jsonb, %s, %s)",
                (
                    campaign.campaign_id,
                    campaign.organization_id,
                    campaign.model_dump_json(),
                    self._token_hash(access_token),
                    campaign.created_at,
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_campaigns SET campaign_json = %s::jsonb WHERE campaign_id = %s",
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT access_token_hash, organization_id FROM concordia_campaigns "
                "WHERE campaign_id = %s",
                (campaign_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(campaign_id)
        token_digest = self._token_hash(access_token)
        if secrets.compare_digest(row["access_token_hash"], token_digest):
            return CampaignPrincipal(
                "campaign-owner", row.get("organization_id", "unknown"), OrganizationRole.OWNER
            )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT grant_json FROM concordia_campaign_access_grants WHERE campaign_id = %s",
                (campaign_id,),
            )
            grant_rows = cursor.fetchall()
        for grant_row in grant_rows:
            grant = CampaignAccessGrant.model_validate_json(_json_text(grant_row["grant_json"]))
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_campaign_access_grants "
                "(grant_id, campaign_id, grant_json, created_at) "
                "VALUES (%s, %s, %s::jsonb, %s)",
                (grant.grant_id, campaign_id, grant.model_dump_json(), created_at),
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT grant_json FROM concordia_campaign_access_grants "
                "WHERE grant_id = %s AND campaign_id = %s",
                (grant_id, campaign_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(grant_id)
        grant = CampaignAccessGrant.model_validate_json(_json_text(row["grant_json"]))
        if grant.revoked_at is not None:
            return
        revoked = grant.model_copy(update={"revoked_at": utc_now()})
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_campaign_access_grants SET grant_json = %s::jsonb "
                "WHERE grant_id = %s",
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT campaign_json FROM concordia_campaigns WHERE campaign_id = %s",
                (campaign_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(campaign_id)
        return Campaign.model_validate_json(_json_text(row["campaign_json"]))

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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_campaign_audit_events "
                "(event_id, campaign_id, event_json, created_at) "
                "VALUES (%s, %s, %s::jsonb, %s)",
                (
                    event.event_id,
                    campaign_id,
                    event.model_dump_json(),
                    event.created_at,
                ),
            )
        return event

    def list_audit_events(self, campaign_id: str) -> tuple[CampaignAuditEvent, ...]:
        self.get_campaign(campaign_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_json FROM concordia_campaign_audit_events "
                "WHERE campaign_id = %s ORDER BY created_at, event_id",
                (campaign_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            CampaignAuditEvent.model_validate_json(_json_text(row["event_json"])) for row in rows
        )

    def create_round(self, campaign_id: str, request: CreateRoundRequest) -> CampaignRound:
        campaign = self.get_campaign(campaign_id)
        _assert_campaign_open(campaign)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (campaign_id,))
            cursor.execute(
                "SELECT COALESCE(MAX((round_json->>'round_number')::int), 0) + 1 AS number "
                "FROM concordia_campaign_rounds WHERE campaign_id = %s",
                (campaign_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Postgres round-number query returned no row")
            number = int(row["number"])
            round_record = CampaignRound(
                round_id=str(uuid.uuid4()),
                campaign_id=campaign.campaign_id,
                round_number=number,
                protocol_version=request.protocol_version,
                assay_context=request.assay_context,
                budget=request.budget,
                batch_size=request.batch_size,
                status=RoundStatus.DRAFT,
                created_at=utc_now(),
            )
            cursor.execute(
                "INSERT INTO concordia_campaign_rounds "
                "(round_id, campaign_id, round_json, created_at) VALUES (%s, %s, %s::jsonb, %s)",
                (
                    round_record.round_id,
                    campaign_id,
                    round_record.model_dump_json(),
                    round_record.created_at,
                ),
            )
        return round_record

    def transition_round(self, round_id: str, status: RoundStatus) -> CampaignRound:
        current = self.get_round(round_id)
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_campaign_rounds SET round_json = %s::jsonb WHERE round_id = %s",
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

    def get_round(self, round_id: str) -> CampaignRound:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT round_json FROM concordia_campaign_rounds WHERE round_id = %s",
                (round_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(round_id)
        return CampaignRound.model_validate_json(_json_text(row["round_json"]))

    def list_rounds(self, campaign_id: str) -> tuple[CampaignRound, ...]:
        self.get_campaign(campaign_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT round_json FROM concordia_campaign_rounds WHERE campaign_id = %s "
                "ORDER BY (round_json->>'round_number')::integer",
                (campaign_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            CampaignRound.model_validate_json(_json_text(row["round_json"])) for row in rows
        )

    def list_candidates(self, round_id: str) -> tuple[Candidate, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT candidate_json FROM concordia_candidates WHERE round_id = %s "
                "ORDER BY candidate_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            Candidate.model_validate_json(_json_text(row["candidate_json"])) for row in rows
        )

    def add_candidate(self, round_id: str, request: AddCandidateRequest) -> Candidate:
        round_record = self.get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        sequence = "".join(request.sequence.upper().split())
        candidate = Candidate(
            candidate_id=str(uuid.uuid4()),
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            sequence=sequence,
            sequence_hash=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            parent_ids=request.parent_ids,
            source=request.source,
            construct_metadata=request.construct_metadata,
            created_at=utc_now(),
        )
        with self._connect() as connection, connection.cursor() as cursor:
            with connection.transaction():
                if request.parent_ids:
                    cursor.execute(
                        "SELECT candidate_id, campaign_id FROM concordia_candidates "
                        "WHERE candidate_id = ANY(%s)",
                        (list(request.parent_ids),),
                    )
                    rows = cursor.fetchall()
                    if len(rows) != len(request.parent_ids) or any(
                        row["campaign_id"] != round_record.campaign_id for row in rows
                    ):
                        raise CampaignConflictError(
                            "candidate parents must belong to this campaign"
                        )
                cursor.execute(
                    "INSERT INTO concordia_candidates "
                    "(candidate_id, campaign_id, round_id, sequence_hash, "
                    "candidate_json, created_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                    (
                        candidate.candidate_id,
                        candidate.campaign_id,
                        round_id,
                        candidate.sequence_hash,
                        candidate.model_dump_json(),
                        candidate.created_at,
                    ),
                )
                for parent_id in request.parent_ids:
                    cursor.execute(
                        "INSERT INTO concordia_candidate_parents (candidate_id, parent_id) "
                        "VALUES (%s, %s)",
                        (candidate.candidate_id, parent_id),
                    )
        return candidate

    def _validate_measurement_candidates(
        self,
        cursor: Any,
        round_record: CampaignRound,
        requests: tuple[RecordMeasurementRequest, ...],
    ) -> None:
        ids = [request.candidate_id for request in requests]
        if not ids:
            return
        cursor.execute(
            "SELECT candidate_id, campaign_id, round_id FROM concordia_candidates "
            "WHERE candidate_id = ANY(%s)",
            (ids,),
        )
        rows = cursor.fetchall()
        if len(rows) != len(set(ids)) or any(
            row["campaign_id"] != round_record.campaign_id
            or row["round_id"] != round_record.round_id
            for row in rows
        ):
            raise CampaignConflictError("measurement candidate is outside this campaign round")

    def record_measurement(self, round_id: str, request: RecordMeasurementRequest) -> Measurement:
        return self.record_measurements(round_id, (request,))[0]

    def record_measurements(
        self, round_id: str, requests: tuple[RecordMeasurementRequest, ...]
    ) -> tuple[Measurement, ...]:
        round_record = self.get_round(round_id)
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
        with self._connect() as connection, connection.cursor() as cursor:
            with connection.transaction():
                self._validate_measurement_candidates(cursor, round_record, requests)
                for measurement in measurements:
                    cursor.execute(
                        "INSERT INTO concordia_measurements "
                        "(measurement_id, round_id, candidate_id, measurement_json, created_at) "
                        "VALUES (%s, %s, %s, %s::jsonb, %s)",
                        (
                            measurement.measurement_id,
                            round_id,
                            measurement.candidate_id,
                            measurement.model_dump_json(),
                            measurement.created_at,
                        ),
                    )
        return measurements

    def list_measurements(self, round_id: str) -> tuple[Measurement, ...]:
        self.get_round(round_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT measurement_json FROM concordia_measurements WHERE round_id = %s "
                "ORDER BY measurement_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            Measurement.model_validate_json(_json_text(row["measurement_json"])) for row in rows
        )

    def freeze_dataset(self, round_id: str, transformation_policy: str) -> DatasetSnapshot:
        round_record = self.get_round(round_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT measurement_id, measurement_json::text AS measurement_json "
                "FROM concordia_measurements WHERE round_id = %s ORDER BY measurement_id",
                (round_id,),
            )
            rows = cursor.fetchall()
            measurement_ids = tuple(row["measurement_id"] for row in rows)
            digest_payload = {
                "measurement_ids": measurement_ids,
                "measurements": [json.loads(_json_text(row["measurement_json"])) for row in rows],
                "transformation_policy": transformation_policy,
            }
            dataset_digest = hashlib.sha256(
                json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
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
            cursor.execute(
                "INSERT INTO concordia_dataset_snapshots "
                "(dataset_id, campaign_id, round_id, dataset_digest, dataset_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (
                    dataset.dataset_id,
                    dataset.campaign_id,
                    round_id,
                    dataset_digest,
                    dataset.model_dump_json(),
                    dataset.created_at,
                ),
            )
        return dataset

    def get_dataset_snapshot(self, dataset_id: str) -> DatasetSnapshot:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT dataset_json FROM concordia_dataset_snapshots WHERE dataset_id = %s",
                (dataset_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(dataset_id)
        return DatasetSnapshot.model_validate_json(_json_text(row["dataset_json"]))

    def list_datasets(self, round_id: str) -> tuple[DatasetSnapshot, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT dataset_json FROM concordia_dataset_snapshots WHERE round_id = %s "
                "ORDER BY dataset_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            DatasetSnapshot.model_validate_json(_json_text(row["dataset_json"])) for row in rows
        )

    def create_study(self, round_id: str, request: CreateStudyRequest) -> CampaignStudy:
        round_record = self.get_round(round_id)
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_campaign_studies "
                "(study_id, campaign_id, round_id, study_json, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s)",
                (
                    study.study_id,
                    study.campaign_id,
                    study.round_id,
                    study.model_dump_json(),
                    study.created_at,
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT study_json FROM concordia_campaign_studies WHERE study_id = %s",
                (study_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(study_id)
        return CampaignStudy.model_validate_json(_json_text(row["study_json"]))

    def list_studies(self, round_id: str) -> tuple[CampaignStudy, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT study_json FROM concordia_campaign_studies WHERE round_id = %s "
                "ORDER BY study_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            CampaignStudy.model_validate_json(_json_text(row["study_json"])) for row in rows
        )

    def freeze_study_record(self, study_id: str) -> CampaignStudy:
        study = self.get_study(study_id)
        _assert_campaign_open(self.get_campaign(study.campaign_id))
        frozen = freeze_study(study)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_campaign_studies SET study_json = %s::jsonb WHERE study_id = %s",
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_campaign_studies SET study_json = %s::jsonb WHERE study_id = %s",
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
        round_record = self.get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        record = CampaignDesignRecord(
            plan=plan,
            campaign_id=round_record.campaign_id,
            round_id=round_id,
            stages=stage_requests(plan),
            created_at=utc_now().isoformat(),
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_design_plans "
                "(plan_id, campaign_id, round_id, plan_json, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s)",
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT plan_json FROM concordia_design_plans WHERE plan_id = %s",
                (plan_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(plan_id)
        return CampaignDesignRecord.model_validate_json(_json_text(row["plan_json"]))

    def get_training_examples(
        self, dataset_id: str, *, metric: str | None = None
    ) -> tuple[ProteinTrainingExample, ...]:
        from concordia.campaigns.training import ProteinTrainingExample

        snapshot = self.get_dataset_snapshot(dataset_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT m.measurement_json, c.candidate_json "
                "FROM concordia_measurements AS m "
                "JOIN concordia_candidates AS c ON c.candidate_id = m.candidate_id "
                "WHERE m.measurement_id = ANY(%s) ORDER BY m.measurement_id",
                (list(snapshot.measurement_ids),),
            )
            rows = cursor.fetchall()
        grouped: dict[tuple[str, str], tuple[str, list[float]]] = {}
        for row in rows:
            measurement = Measurement.model_validate_json(_json_text(row["measurement_json"]))
            candidate = Candidate.model_validate_json(_json_text(row["candidate_json"]))
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
        round_record = self.get_round(round_id)
        with self._connect() as connection, connection.cursor() as cursor:
            if candidate_ids:
                cursor.execute(
                    "SELECT candidate_id FROM concordia_candidates "
                    "WHERE round_id = %s AND candidate_id = ANY(%s)",
                    (round_id, list(candidate_ids)),
                )
                rows = cursor.fetchall()
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
            cursor.execute(
                "INSERT INTO concordia_recommendations "
                "(recommendation_id, campaign_id, round_id, recommendation_json, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s)",
                (
                    recommendation.recommendation_id,
                    recommendation.campaign_id,
                    round_id,
                    recommendation.model_dump_json(),
                    recommendation.created_at,
                ),
            )
        return recommendation

    def record_model_run(self, round_id: str, request: RecordModelRunRequest) -> CampaignModelRun:
        round_record = self.get_round(round_id)
        _assert_campaign_open(self.get_campaign(round_record.campaign_id))
        _assert_round_writable(round_record)
        with self._connect() as connection, connection.cursor() as cursor:
            if request.candidate_ids:
                cursor.execute(
                    "SELECT candidate_id FROM concordia_candidates "
                    "WHERE round_id = %s AND candidate_id = ANY(%s)",
                    (round_id, list(request.candidate_ids)),
                )
                if len(cursor.fetchall()) != len(set(request.candidate_ids)):
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
                scientific_use_allowed=False,
                created_at=utc_now(),
                input_digest=hashlib.sha256(
                    json.dumps(request.input_artifact_digests, separators=(",", ":")).encode()
                ).hexdigest(),
                parameter_digest=hashlib.sha256(
                    json.dumps(request.parameters, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            )
            cursor.execute(
                "INSERT INTO concordia_model_runs "
                "(model_run_id, campaign_id, round_id, model_run_json, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s)",
                (
                    model_run.model_run_id,
                    model_run.campaign_id,
                    round_id,
                    model_run.model_dump_json(),
                    model_run.created_at,
                ),
            )
        return model_run

    def get_model_run(self, model_run_id: str) -> CampaignModelRun:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_run_json FROM concordia_model_runs WHERE model_run_id = %s",
                (model_run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(model_run_id)
        return CampaignModelRun.model_validate_json(_json_text(row["model_run_json"]))

    def clone_model_run_for_replay(self, model_run_id: str) -> CampaignModelRun:
        source = self.get_model_run(model_run_id)
        round_record = self.get_round(source.round_id)
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_model_runs "
                "(model_run_id, campaign_id, round_id, model_run_json, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s)",
                (
                    replay.model_run_id,
                    replay.campaign_id,
                    replay.round_id,
                    replay.model_dump_json(),
                    replay.created_at,
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_run_json FROM concordia_model_runs WHERE round_id = %s "
                "ORDER BY model_run_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            CampaignModelRun.model_validate_json(_json_text(row["model_run_json"])) for row in rows
        )

    def list_recommendations(self, round_id: str) -> tuple[Recommendation, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT recommendation_json FROM concordia_recommendations WHERE round_id = %s "
                "ORDER BY recommendation_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            Recommendation.model_validate_json(_json_text(row["recommendation_json"]))
            for row in rows
        )

    def get_recommendation(self, recommendation_id: str) -> Recommendation:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT recommendation_json FROM concordia_recommendations "
                "WHERE recommendation_id = %s",
                (recommendation_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(recommendation_id)
        return Recommendation.model_validate_json(_json_text(row["recommendation_json"]))

    def get_candidate(self, candidate_id: str) -> Candidate:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT candidate_json FROM concordia_candidates WHERE candidate_id = %s",
                (candidate_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(candidate_id)
        return Candidate.model_validate_json(_json_text(row["candidate_json"]))

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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_model_runs SET model_run_json = %s::jsonb "
                "WHERE model_run_id = %s",
                (completed.model_dump_json(), model_run_id),
            )
        return completed

    def enqueue_model_job(
        self, campaign_id: str, request: EnqueueModelJobRequest
    ) -> CampaignModelJob:
        self.get_campaign(campaign_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_runs.campaign_id, model_runs.round_id, "
                "(rounds.round_json->>'budget')::double precision AS budget "
                "FROM concordia_model_runs AS model_runs "
                "JOIN concordia_campaign_rounds AS rounds "
                "ON rounds.round_id = model_runs.round_id "
                "WHERE model_runs.model_run_id = %s",
                (request.model_run_id,),
            )
            row = cursor.fetchone()
            if row is None or row["campaign_id"] != campaign_id:
                raise CampaignConflictError("model run does not belong to campaign")
            _assert_campaign_open(self.get_campaign(campaign_id))
            _assert_round_writable(self.get_round(row["round_id"]))
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
            cursor.execute(
                "INSERT INTO concordia_model_jobs "
                "(job_id, campaign_id, round_id, model_run_id, status, job_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                (
                    job.job_id,
                    campaign_id,
                    job.round_id,
                    job.model_run_id,
                    job.status,
                    job.model_dump_json(),
                    now,
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT job_json FROM concordia_model_jobs WHERE job_id = %s", (job_id,))
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(job_id)
        return CampaignModelJob.model_validate_json(_json_text(row["job_json"]))

    def list_model_jobs(self, campaign_id: str) -> tuple[CampaignModelJob, ...]:
        self.get_campaign(campaign_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_json FROM concordia_model_jobs WHERE campaign_id = %s ORDER BY job_id",
                (campaign_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            CampaignModelJob.model_validate_json(_json_text(row["job_json"])) for row in rows
        )

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
        with self._connect() as connection, connection.cursor() as cursor:
            with connection.transaction():
                query = (
                    "SELECT job_json FROM concordia_model_jobs "
                    "WHERE status IN ('queued', 'leased') "
                    "AND (status = 'queued' OR lease_expires_at <= %s) "
                    "AND (job_json->>'cancel_requested')::boolean = false "
                    "AND (job_json->>'attempt')::int < (job_json->>'max_attempts')::int "
                )
                params: list[Any] = [claimed_at]
                if job_id is not None:
                    query += "AND job_id = %s "
                    params.append(job_id)
                query += "ORDER BY created_at, job_id LIMIT 1 FOR UPDATE SKIP LOCKED"
                cursor.execute(query, params)
                row = cursor.fetchone()
                if row is None:
                    return None
                current = CampaignModelJob.model_validate_json(_json_text(row["job_json"]))
                claimed = current.model_copy(
                    update={
                        "status": ModelJobStatus.LEASED,
                        "attempt": current.attempt + 1,
                        "lease_owner": owner,
                        "lease_expires_at": expiry,
                    }
                )
                cursor.execute(
                    "UPDATE concordia_model_jobs SET status = %s, lease_owner = %s, "
                    "lease_expires_at = %s, job_json = %s::jsonb WHERE job_id = %s",
                    (claimed.status, owner, expiry, claimed.model_dump_json(), claimed.job_id),
                )
        return claimed

    def mark_model_job_submitted(
        self, job_id: str, owner: str, provider_request_id: str
    ) -> CampaignModelJob:
        current = self.get_model_job(job_id)
        if current.status is not ModelJobStatus.LEASED or current.lease_owner != owner:
            raise CampaignConflictError("worker does not own model job lease")
        submitted = current.model_copy(update={"provider_request_id": provider_request_id})
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_model_jobs SET job_json = %s::jsonb WHERE job_id = %s",
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_model_jobs SET status = %s, lease_owner = NULL, "
                "lease_expires_at = NULL, job_json = %s::jsonb WHERE job_id = %s",
                (status, finished.model_dump_json(), job_id),
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_model_jobs SET status = %s, lease_owner = NULL, "
                "lease_expires_at = NULL, job_json = %s::jsonb WHERE job_id = %s",
                (queued.status, queued.model_dump_json(), job_id),
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_model_jobs SET status = %s, lease_owner = NULL, "
                "lease_expires_at = NULL, job_json = %s::jsonb WHERE job_id = %s",
                (cancelled.status, cancelled.model_dump_json(), job_id),
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

    def create_evidence_claim(
        self, round_id: str, request: CreateEvidenceClaimRequest
    ) -> EvidenceClaim:
        round_record = self.get_round(round_id)
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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_evidence_claims "
                "(claim_id, campaign_id, round_id, verification_status, claim_json, "
                "created_at) VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (
                    claim.claim_id,
                    claim.campaign_id,
                    round_id,
                    claim.verification_status,
                    claim.model_dump_json(),
                    claim.created_at,
                ),
            )
        return claim

    def get_evidence_claim(self, claim_id: str) -> EvidenceClaim:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT claim_json FROM concordia_evidence_claims WHERE claim_id = %s", (claim_id,)
            )
            row = cursor.fetchone()
        if row is None:
            raise CampaignNotFoundError(claim_id)
        return EvidenceClaim.model_validate_json(_json_text(row["claim_json"]))

    def list_evidence_claims(self, round_id: str) -> tuple[EvidenceClaim, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT claim_json FROM concordia_evidence_claims WHERE round_id = %s "
                "ORDER BY claim_id",
                (round_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            EvidenceClaim.model_validate_json(_json_text(row["claim_json"])) for row in rows
        )

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
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_evidence_claims SET verification_status = %s, "
                "claim_json = %s::jsonb WHERE claim_id = %s",
                (status, verified.model_dump_json(), claim_id),
            )
        return verified


__all__ = [
    "CAMPAIGN_SCHEMA_VERSION",
    "CAMPAIGN_SCHEMA_STATEMENTS",
    "PostgresCampaignStore",
    "migrate_campaign_schema",
    "schema_statements",
]
