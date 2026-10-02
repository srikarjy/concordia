"""Optional Supabase/Postgres-backed persistence for the interactive endpoints.

Every gateway and queue in this package defaults to a local SQLite file. On a
Hugging Face Space, that file is ephemeral — wiped on every redeploy or
restart. When ``CONCORDIA_DATABASE_URL`` is set, ``api/workspace.py`` swaps in
the classes here instead, backed by a real Postgres database (a Supabase
project in practice), so rate limits, caches, and job history survive
redeploys. Local development and the entire existing test suite are
unaffected: nothing here is imported unless that environment variable is set.

The three Postgres tables (``concordia_rate_limit_requests``,
``concordia_result_cache``, ``concordia_forward_jobs``) are namespaced by a
``concordia_`` prefix and created by a Supabase migration
(``create_concordia_interactive_state_tables``); see ``docs/deployment.md``.
They are shared across every namespace (one physical table per concern, not
per gateway) to keep the schema small.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from concordia.genomics.rate_limiting import Clock, RateLimitExceededError, SystemClock


def _connect(dsn: str) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def _count(cursor: psycopg.Cursor[dict[str, Any]]) -> int:
    row = cursor.fetchone()
    assert row is not None  # a COUNT(*) query always returns exactly one row
    return int(row["count"])


class PostgresRateLimiter:
    """Drop-in Postgres replacement for ``SqliteRateLimiter``."""

    def __init__(
        self,
        *,
        dsn: str,
        namespace: str,
        per_client_limit: int,
        per_client_window_seconds: int,
        global_daily_limit: int,
        clock: Clock | None = None,
    ):
        self.dsn = dsn
        self.namespace = namespace
        self.per_client_limit = per_client_limit
        self.per_client_window_seconds = per_client_window_seconds
        self.global_daily_limit = global_daily_limit
        self._clock: Clock = clock or SystemClock()

    def check_and_record(self, client_id: str) -> None:
        now = self._clock.time()
        window_start = now - self.per_client_window_seconds
        day_start = now - 86_400
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM concordia_rate_limit_requests "
                "WHERE namespace = %s AND requested_at < %s",
                (self.namespace, day_start),
            )
            cursor.execute(
                "SELECT COUNT(*) AS count FROM concordia_rate_limit_requests "
                "WHERE namespace = %s AND client_id = %s AND requested_at >= %s",
                (self.namespace, client_id, window_start),
            )
            if _count(cursor) >= self.per_client_limit:
                raise RateLimitExceededError(
                    "per-client rate limit exceeded",
                    retry_after_seconds=self.per_client_window_seconds,
                )
            cursor.execute(
                "SELECT COUNT(*) AS count FROM concordia_rate_limit_requests "
                "WHERE namespace = %s AND requested_at >= %s",
                (self.namespace, day_start),
            )
            if _count(cursor) >= self.global_daily_limit:
                raise RateLimitExceededError(
                    "daily quota exhausted", retry_after_seconds=86_400
                )
            cursor.execute(
                "INSERT INTO concordia_rate_limit_requests "
                "(namespace, client_id, requested_at) VALUES (%s, %s, %s)",
                (self.namespace, client_id, now),
            )


class PostgresRateLimitedCache:
    """Drop-in Postgres replacement for the gateways' rate-limit + cache pattern."""

    def __init__(
        self,
        *,
        dsn: str,
        namespace: str,
        per_client_limit: int,
        per_client_window_seconds: int,
        global_daily_limit: int,
        clock: Clock | None = None,
    ):
        self._limiter = PostgresRateLimiter(
            dsn=dsn,
            namespace=namespace,
            per_client_limit=per_client_limit,
            per_client_window_seconds=per_client_window_seconds,
            global_daily_limit=global_daily_limit,
            clock=clock,
        )
        self.dsn = dsn
        self.namespace = namespace

    def get_cached(self, request_key: str) -> str | None:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT result_json::text AS result_json FROM concordia_result_cache "
                "WHERE namespace = %s AND request_key = %s",
                (self.namespace, request_key),
            )
            row = cursor.fetchone()
        return row["result_json"] if row else None

    def check_and_record_rate_limit(self, client_id: str) -> None:
        self._limiter.check_and_record(client_id)

    def store(self, request_key: str, result_json: str, created_at: float) -> None:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_result_cache "
                "(namespace, request_key, result_json, created_at) "
                "VALUES (%s, %s, %s::jsonb, %s) "
                "ON CONFLICT (namespace, request_key) "
                "DO UPDATE SET result_json = EXCLUDED.result_json, "
                "created_at = EXCLUDED.created_at",
                (self.namespace, request_key, result_json, created_at),
            )


class PostgresForwardJobStore:
    """Drop-in Postgres replacement for ``Evo2ForwardJobQueue``'s SQLite table."""

    def __init__(self, *, dsn: str):
        self.dsn = dsn

    def insert_queued(self, job_id: str, client_id: str, submitted_at: float) -> None:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO concordia_forward_jobs "
                "(job_id, client_id, status, submitted_at) VALUES (%s, %s, 'QUEUED', %s)",
                (job_id, client_id, submitted_at),
            )

    def update_status(self, job_id: str, status: str) -> None:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_forward_jobs SET status = %s WHERE job_id = %s",
                (status, job_id),
            )

    def mark_terminal(
        self,
        job_id: str,
        *,
        status: str,
        completed_at: float,
        result_json: str | None = None,
        error: str | None = None,
    ) -> None:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE concordia_forward_jobs SET status = %s, completed_at = %s, "
                "result_json = %s::jsonb, error = %s WHERE job_id = %s",
                (status, completed_at, result_json, error, job_id),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_id, status, submitted_at, completed_at, "
                "result_json::text AS result_json, error "
                "FROM concordia_forward_jobs WHERE job_id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "submitted_at": row["submitted_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
        }

    def count_recent(self, client_id: str, window_start: float) -> int:
        with _connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM concordia_forward_jobs "
                "WHERE client_id = %s AND submitted_at >= %s",
                (client_id, window_start),
            )
            return _count(cursor)
