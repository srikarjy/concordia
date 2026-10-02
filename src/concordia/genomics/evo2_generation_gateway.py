"""Rate-limited, cached gateway for interactive hosted Evo2 generation.

This sits in front of ``NvidiaHostedEvo2GenerationRunner`` so a public,
multi-tenant deployment can let visitors trigger real NVIDIA calls without
any visitor ever seeing ``NVIDIA_API_KEY`` and without one visitor exhausting
the shared hosted-API quota for everyone else.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from concordia.genomics.evo2_nvidia import (
    NvidiaHostedEvo2GenerationRunner,
    NvidiaHostedGenerationResult,
)
from concordia.genomics.rate_limiting import Clock, RateLimitExceededError, SystemClock
from concordia.genomics.schema import GenomicSequence

if TYPE_CHECKING:
    from concordia.genomics.postgres_backend import PostgresRateLimitedCache

__all__ = ["Evo2GenerationGateway", "RateLimitExceededError"]


def _request_key(
    sequence: str,
    num_tokens: int,
    temperature: float,
    top_k: int,
    top_p: float,
    random_seed: int,
) -> str:
    payload = json.dumps(
        {
            "sequence": sequence,
            "num_tokens": num_tokens,
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "random_seed": random_seed,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Evo2GenerationGateway:
    """Fixed-window rate limiting plus content-hash caching around one runner."""

    def __init__(
        self,
        runner: NvidiaHostedEvo2GenerationRunner,
        *,
        database_path: str | Path | None = None,
        postgres_dsn: str | None = None,
        per_client_limit: int = 5,
        per_client_window_seconds: int = 60,
        global_daily_limit: int = 200,
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
                namespace="evo2_generation",
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
                """
                CREATE TABLE IF NOT EXISTS client_requests (
                    client_id TEXT NOT NULL,
                    requested_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_cache (
                    request_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_client_requests_client_id "
                "ON client_requests(client_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_client_requests_requested_at "
                "ON client_requests(requested_at)"
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
                "SELECT COUNT(*) FROM client_requests "
                "WHERE client_id = ? AND requested_at >= ?",
                (client_id, window_start),
            ).fetchone()[0]
            if client_count >= self.per_client_limit:
                raise RateLimitExceededError(
                    "per-client rate limit exceeded",
                    retry_after_seconds=self.per_client_window_seconds,
                )
            global_count = connection.execute(
                "SELECT COUNT(*) FROM client_requests WHERE requested_at >= ?",
                (day_start,),
            ).fetchone()[0]
            if global_count >= self.global_daily_limit:
                raise RateLimitExceededError(
                    "daily hosted-generation quota exhausted",
                    retry_after_seconds=86_400,
                )
            connection.execute(
                "INSERT INTO client_requests (client_id, requested_at) VALUES (?, ?)",
                (client_id, now),
            )

    def _cached_result(self, request_key: str) -> NvidiaHostedGenerationResult | None:
        if self._postgres is not None:
            cached_json = self._postgres.get_cached(request_key)
            return (
                NvidiaHostedGenerationResult.model_validate_json(cached_json)
                if cached_json
                else None
            )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM generation_cache WHERE request_key = ?",
                (request_key,),
            ).fetchone()
        if row is None:
            return None
        return NvidiaHostedGenerationResult.model_validate_json(row["result_json"])

    def _store_result(self, request_key: str, result: NvidiaHostedGenerationResult) -> None:
        if self._postgres is not None:
            self._postgres.store(request_key, result.model_dump_json(), self._now())
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO generation_cache "
                "(request_key, result_json, created_at) VALUES (?, ?, ?)",
                (request_key, result.model_dump_json(), self._now()),
            )

    def generate(
        self,
        *,
        client_id: str,
        sequence: GenomicSequence,
        num_tokens: int = 8,
        temperature: float = 0.7,
        top_k: int = 3,
        top_p: float = 0.0,
        random_seed: int = 1729,
    ) -> NvidiaHostedGenerationResult:
        request_key = _request_key(
            sequence.sequence, num_tokens, temperature, top_k, top_p, random_seed
        )
        cached = self._cached_result(request_key)
        if cached is not None:
            return cached
        self._check_and_record_rate_limit(client_id)
        result = self.runner.generate(
            sequence,
            num_tokens=num_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            random_seed=random_seed,
        )
        self._store_result(request_key, result)
        return result
