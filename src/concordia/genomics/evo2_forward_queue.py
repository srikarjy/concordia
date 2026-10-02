"""Single-flight, rate-limited job queue for interactive Evo2 forward scoring.

Unlike hosted generation (fast, synchronous, cheap), a real forward pass loads
a 13.77GB checkpoint on a time-boxed ZeroGPU allocation and may take minutes
or fail outright — this has never been run end to end. A public deployment
cannot let concurrent visitors each trigger a ZeroGPU job: this queue allows
exactly one in-flight job at a time and makes every other request wait or be
rejected, so one slow or hung job cannot be amplified by concurrent traffic.

Defaults to a local SQLite file. Pass ``postgres_dsn`` instead (set by
``api/workspace.py`` when ``CONCORDIA_DATABASE_URL`` is configured) so job
history survives a Hugging Face Space's ephemeral filesystem across
redeploys. The single-flight lock itself stays in-process either way — it
protects this one worker process's concurrency, not cross-process state.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from concordia.genomics.rate_limiting import RateLimitExceededError
from concordia.genomics.schema import GenomicSequence

if TYPE_CHECKING:
    from concordia.genomics.postgres_backend import PostgresForwardJobStore

__all__ = ["Evo2ForwardJobQueue", "QueueBusyError", "JobNotFoundError", "RateLimitExceededError"]


class QueueBusyError(RuntimeError):
    """Raised when a forward-scoring job is already in flight."""


class JobNotFoundError(LookupError):
    pass


class ForwardScorer(Protocol):
    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, Any]: ...


class Evo2ForwardJobQueue:
    """SQLite- or Postgres-backed job record plus an in-process single-flight lock."""

    def __init__(
        self,
        scorer: ForwardScorer,
        *,
        database_path: str | Path | None = None,
        postgres_dsn: str | None = None,
        checkpoint: str,
        target: str,
        per_client_limit: int = 2,
        per_client_window_seconds: int = 3_600,
    ):
        self.scorer = scorer
        self.checkpoint = checkpoint
        self.target = target
        self.per_client_limit = per_client_limit
        self.per_client_window_seconds = per_client_window_seconds
        self._execution_lock = threading.Lock()
        self._postgres: PostgresForwardJobStore | None = None
        if postgres_dsn is not None:
            from concordia.genomics.postgres_backend import PostgresForwardJobStore as _PG

            self._postgres = _PG(dsn=postgres_dsn)
            return
        if database_path is None:
            raise ValueError("either database_path or postgres_dsn is required")
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS forward_jobs (
                    job_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at REAL NOT NULL,
                    completed_at REAL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_forward_jobs_client "
                "ON forward_jobs(client_id, submitted_at)"
            )

    def _check_and_record_rate_limit(self, client_id: str) -> None:
        now = time.time()
        window_start = now - self.per_client_window_seconds
        if self._postgres is not None:
            count = self._postgres.count_recent(client_id, window_start)
        else:
            with self._connect() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM forward_jobs WHERE client_id = ? AND submitted_at >= ?",
                    (client_id, window_start),
                ).fetchone()[0]
        if count >= self.per_client_limit:
            raise RateLimitExceededError(
                "per-client forward-scoring limit exceeded",
                retry_after_seconds=self.per_client_window_seconds,
            )

    def submit(self, *, client_id: str, sequence: GenomicSequence) -> str:
        """Record a queued job and return its id immediately.

        This does not run the job. The caller (typically an API handler) is
        responsible for invoking ``run`` on a background thread with the
        returned job id and the same sequence, then letting visitors poll
        ``get`` for the result — a ZeroGPU forward pass can take minutes and
        must never block the HTTP request that submitted it.
        """

        self._check_and_record_rate_limit(client_id)
        job_id = str(uuid.uuid4())
        if self._postgres is not None:
            self._postgres.insert_queued(job_id, client_id, time.time())
            return job_id
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO forward_jobs (job_id, client_id, status, submitted_at) "
                "VALUES (?, ?, 'QUEUED', ?)",
                (job_id, client_id, time.time()),
            )
        return job_id

    def run(self, job_id: str, sequence: GenomicSequence) -> None:
        """Execute a previously submitted job. Blocking; run on a worker thread.

        At most one call to ``run`` across this queue instance executes the
        scorer at a time. A concurrent call is rejected immediately as
        ``REJECTED_BUSY`` rather than queued, since a second visitor should
        not silently wait behind an unbounded ZeroGPU job.
        """

        acquired = self._execution_lock.acquire(blocking=False)
        if not acquired:
            self._mark_terminal(
                job_id,
                status="REJECTED_BUSY",
                error="another forward-scoring job is already in flight",
            )
            raise QueueBusyError("another forward-scoring job is already in flight")

        try:
            self._update_status(job_id, "RUNNING")
            try:
                result = self.scorer.score(
                    sequence, checkpoint=self.checkpoint, target=self.target
                )
                self._mark_terminal(job_id, status="COMPLETED", result_json=json.dumps(result))
            except Exception as error:  # noqa: BLE001 - always record, never lose the job
                self._mark_terminal(job_id, status="FAILED", error=str(error))
        finally:
            self._execution_lock.release()

    def _update_status(self, job_id: str, status: str) -> None:
        if self._postgres is not None:
            self._postgres.update_status(job_id, status)
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE forward_jobs SET status = ? WHERE job_id = ?", (status, job_id)
            )

    def _mark_terminal(
        self,
        job_id: str,
        *,
        status: str,
        result_json: str | None = None,
        error: str | None = None,
    ) -> None:
        completed_at = time.time()
        if self._postgres is not None:
            self._postgres.mark_terminal(
                job_id,
                status=status,
                completed_at=completed_at,
                result_json=result_json,
                error=error,
            )
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE forward_jobs SET status = ?, completed_at = ?, "
                "result_json = ?, error = ? WHERE job_id = ?",
                (status, completed_at, result_json, error, job_id),
            )

    def get(self, job_id: str) -> dict[str, Any]:
        if self._postgres is not None:
            record = self._postgres.get(job_id)
            if record is None:
                raise JobNotFoundError(job_id)
            return record
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forward_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "submitted_at": row["submitted_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
        }
