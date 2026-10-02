"""Rate-limited, cached gateway for interactive hosted Boltz-2 prediction.

Mirrors ``EsmFoldGateway``, with tighter limits: Boltz-2 is a heavier,
slower model (recycling/diffusion steps, possible NVCF long-polling up to
minutes) than ESMFold was, so the shared NVIDIA_API_KEY quota needs more
protection per call.

Defaults to a local SQLite file. Pass ``postgres_dsn`` instead (set by
``api/workspace.py`` when ``CONCORDIA_DATABASE_URL`` is configured) so the
cache and rate-limit state survive a Hugging Face Space's ephemeral
filesystem across redeploys.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzResult, NvidiaHostedBoltzRunner
from concordia.genomics.rate_limiting import Clock, RateLimitExceededError, SystemClock

if TYPE_CHECKING:
    from concordia.genomics.postgres_backend import PostgresRateLimitedCache

__all__ = ["BoltzGateway", "RateLimitExceededError"]


class BoltzGateway:
    def __init__(
        self,
        runner: NvidiaHostedBoltzRunner,
        *,
        database_path: str | Path | None = None,
        postgres_dsn: str | None = None,
        per_client_limit: int = 3,
        per_client_window_seconds: int = 3_600,
        global_daily_limit: int = 50,
        clock: Clock | None = None,
    ):
        self.runner = runner
        self.per_client_limit = per_client_limit
        self.per_client_window_seconds = per_client_window_seconds
        self.global_daily_limit = global_daily_limit
        self._clock: Clock = clock or SystemClock()
        self._postgres: PostgresRateLimitedCache | None = None
        if postgres_dsn is not None:
            from concordia.genomics.postgres_backend import PostgresRateLimitedCache as _PG

            self._postgres = _PG(
                dsn=postgres_dsn,
                namespace="boltz",
                per_client_limit=per_client_limit,
                per_client_window_seconds=per_client_window_seconds,
                global_daily_limit=global_daily_limit,
                clock=self._clock,
            )
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
                "CREATE TABLE IF NOT EXISTS client_requests "
                "(client_id TEXT NOT NULL, requested_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS prediction_cache "
                "(request_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, "
                "created_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_boltz_client_requests "
                "ON client_requests(client_id, requested_at)"
            )

    def _now(self) -> float:
        return self._clock.time()

    def _check_and_record_rate_limit(self, client_id: str) -> None:
        if self._postgres is not None:
            self._postgres.check_and_record_rate_limit(client_id)
            return
        now = self._now()
        window_start = now - self.per_client_window_seconds
        day_start = now - 86_400
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM client_requests WHERE requested_at < ?", (day_start,)
            )
            client_count = connection.execute(
                "SELECT COUNT(*) FROM client_requests WHERE client_id = ? AND requested_at >= ?",
                (client_id, window_start),
            ).fetchone()[0]
            if client_count >= self.per_client_limit:
                raise RateLimitExceededError(
                    "per-client rate limit exceeded",
                    retry_after_seconds=self.per_client_window_seconds,
                )
            global_count = connection.execute(
                "SELECT COUNT(*) FROM client_requests WHERE requested_at >= ?", (day_start,)
            ).fetchone()[0]
            if global_count >= self.global_daily_limit:
                raise RateLimitExceededError(
                    "daily hosted-structure-prediction quota exhausted",
                    retry_after_seconds=86_400,
                )
            connection.execute(
                "INSERT INTO client_requests (client_id, requested_at) VALUES (?, ?)",
                (client_id, now),
            )

    def predict(self, *, client_id: str, sequence: str) -> NvidiaHostedBoltzResult:
        request_key = hashlib.sha256(sequence.strip().upper().encode("ascii")).hexdigest()
        if self._postgres is not None:
            cached_json = self._postgres.get_cached(request_key)
            if cached_json:
                return NvidiaHostedBoltzResult.model_validate_json(cached_json)
            self._check_and_record_rate_limit(client_id)
            result = self.runner.predict(sequence)
            self._postgres.store(request_key, result.model_dump_json(), self._now())
            return result
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM prediction_cache WHERE request_key = ?",
                (request_key,),
            ).fetchone()
        if row is not None:
            return NvidiaHostedBoltzResult.model_validate_json(row["result_json"])
        self._check_and_record_rate_limit(client_id)
        result = self.runner.predict(sequence)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO prediction_cache "
                "(request_key, result_json, created_at) VALUES (?, ?, ?)",
                (request_key, result.model_dump_json(), self._now()),
            )
        return result
