"""SQLite-backed job leases for isolated local worker processes."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class JobState(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    owner: str
    expires_at: datetime
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    state: JobState
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    cancel_requested: bool


class LeaseConflictError(RuntimeError):
    pass


class SQLiteJobQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    run_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                VALUES (2, CURRENT_TIMESTAMP);
                """
            )

    def enqueue(self, run_id: str, *, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max attempts must be positive")
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO jobs
                   (run_id, state, max_attempts, created_at, updated_at)
                   VALUES (?, 'QUEUED', ?, ?, ?)""",
                (run_id, max_attempts, now, now),
            )

    def claim(
        self,
        owner: str,
        *,
        lease_seconds: float = 30,
        now: datetime | None = None,
        run_id: str | None = None,
    ) -> JobLease | None:
        if not owner:
            raise ValueError("lease owner is required")
        if lease_seconds <= 0:
            raise ValueError("lease duration must be positive")
        claimed_at = now or datetime.now(UTC)
        expires_at = claimed_at + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            parameters: list[object] = [claimed_at.isoformat()]
            run_filter = ""
            if run_id is not None:
                run_filter = "AND run_id = ?"
                parameters.append(run_id)
            row = connection.execute(
                f"""SELECT * FROM jobs
                    WHERE cancel_requested = 0
                      AND attempts < max_attempts
                      AND (state = 'QUEUED' OR
                           (state = 'LEASED' AND lease_expires_at <= ?))
                      {run_filter}
                    ORDER BY created_at, run_id
                    LIMIT 1""",
                parameters,
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            attempt = int(row["attempts"]) + 1
            connection.execute(
                """UPDATE jobs
                   SET state = 'LEASED', lease_owner = ?, lease_expires_at = ?,
                       attempts = ?, updated_at = ?
                   WHERE run_id = ?""",
                (
                    owner,
                    expires_at.isoformat(),
                    attempt,
                    claimed_at.isoformat(),
                    row["run_id"],
                ),
            )
            connection.commit()
        return JobLease(
            run_id=row["run_id"],
            owner=owner,
            expires_at=expires_at,
            attempt=attempt,
            max_attempts=row["max_attempts"],
        )

    def heartbeat(
        self,
        lease: JobLease,
        *,
        lease_seconds: float = 30,
        now: datetime | None = None,
    ) -> JobLease:
        heartbeat_at = now or datetime.now(UTC)
        expires_at = heartbeat_at + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                   WHERE run_id = ? AND state = 'LEASED' AND lease_owner = ?
                     AND cancel_requested = 0 AND lease_expires_at > ?""",
                (
                    expires_at.isoformat(),
                    heartbeat_at.isoformat(),
                    lease.run_id,
                    lease.owner,
                    heartbeat_at.isoformat(),
                ),
            )
        if cursor.rowcount != 1:
            raise LeaseConflictError("worker no longer owns the job lease")
        return lease.model_copy(update={"expires_at": expires_at})

    def finish(self, lease: JobLease, state: JobState = JobState.DONE) -> None:
        if state not in {JobState.DONE, JobState.FAILED, JobState.CANCELLED}:
            raise ValueError("job can only finish in a terminal operational state")
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs
                   SET state = ?, lease_owner = NULL, lease_expires_at = NULL,
                       updated_at = ?
                   WHERE run_id = ? AND state = 'LEASED' AND lease_owner = ?""",
                (state, datetime.now(UTC).isoformat(), lease.run_id, lease.owner),
            )
        if cursor.rowcount != 1:
            if self.get(lease.run_id).state is state:
                return
            raise LeaseConflictError("worker no longer owns the job lease")

    def release_infrastructure_failure(self, lease: JobLease) -> bool:
        exhausted = lease.attempt >= lease.max_attempts
        state = JobState.FAILED if exhausted else JobState.QUEUED
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs
                   SET state = ?, lease_owner = NULL, lease_expires_at = NULL,
                       updated_at = ?
                   WHERE run_id = ? AND state = 'LEASED' AND lease_owner = ?""",
                (state, datetime.now(UTC).isoformat(), lease.run_id, lease.owner),
            )
        if cursor.rowcount != 1:
            raise LeaseConflictError("worker no longer owns the job lease")
        return exhausted

    def request_cancel(self, run_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs
                   SET state = 'CANCELLED', cancel_requested = 1,
                       lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                   WHERE run_id = ? AND state NOT IN ('DONE', 'FAILED', 'CANCELLED')""",
                (datetime.now(UTC).isoformat(), run_id),
            )
        if cursor.rowcount == 0:
            record = self.get(run_id)
            if record.state is not JobState.CANCELLED:
                raise LeaseConflictError("job is already terminal")

    def is_cancel_requested(self, run_id: str) -> bool:
        return self.get(run_id).cancel_requested

    def get(self, run_id: str) -> JobRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise LookupError(run_id)
        return JobRecord(
            run_id=row["run_id"],
            state=row["state"],
            lease_owner=row["lease_owner"],
            lease_expires_at=(
                datetime.fromisoformat(row["lease_expires_at"])
                if row["lease_expires_at"]
                else None
            ),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            cancel_requested=bool(row["cancel_requested"]),
        )

    def exhausted_expired(self, *, now: datetime | None = None) -> tuple[str, ...]:
        checked_at = now or datetime.now(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT run_id FROM jobs
                   WHERE state = 'LEASED' AND attempts >= max_attempts
                     AND lease_expires_at <= ?""",
                (checked_at.isoformat(),),
            ).fetchall()
            run_ids = tuple(str(row["run_id"]) for row in rows)
            for exhausted_run_id in run_ids:
                connection.execute(
                    """UPDATE jobs SET state = 'FAILED', lease_owner = NULL,
                       lease_expires_at = NULL, updated_at = ? WHERE run_id = ?""",
                    (checked_at.isoformat(), exhausted_run_id),
                )
            connection.commit()
        return run_ids
