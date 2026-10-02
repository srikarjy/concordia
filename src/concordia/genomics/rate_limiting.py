"""Shared rate-limiting primitives for the interactive Evo2/ESMFold endpoints.

``RateLimitExceededError`` is raised by every gateway so a single FastAPI
exception handler in ``api/workspace.py`` can catch all of them.
``Clock``/``_SystemClock`` let each gateway's tests substitute a fake clock
without each module redefining the same tiny protocol.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Protocol


class RateLimitExceededError(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class Clock(Protocol):
    def time(self) -> float: ...


class SystemClock:
    def time(self) -> float:
        return time.time()


class SqliteRateLimiter:
    """Generic per-client + global fixed-window limiter, no caching.

    For endpoints whose result shouldn't be cached (each call is meant to
    produce something fresh, e.g. a new randomized simulation) but that
    still need the same public-deployment quota protection as the
    gateways in this package.
    """

    def __init__(
        self,
        *,
        database_path: str | Path,
        table_name: str = "client_requests",
        per_client_limit: int = 5,
        per_client_window_seconds: int = 60,
        global_daily_limit: int = 200,
        clock: Clock | None = None,
    ):
        if not table_name.isidentifier():
            raise ValueError("table_name must be a valid identifier")
        self.table_name = table_name
        self.per_client_limit = per_client_limit
        self.per_client_window_seconds = per_client_window_seconds
        self.global_daily_limit = global_daily_limit
        self._clock: Clock = clock or SystemClock()
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
                f"CREATE TABLE IF NOT EXISTS {self.table_name} "  # noqa: S608 - validated identifier
                "(client_id TEXT NOT NULL, requested_at REAL NOT NULL)"
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name} "  # noqa: S608
                f"ON {self.table_name}(client_id, requested_at)"
            )

    def check_and_record(self, client_id: str) -> None:
        now = self._clock.time()
        window_start = now - self.per_client_window_seconds
        day_start = now - 86_400
        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM {self.table_name} WHERE requested_at < ?",  # noqa: S608
                (day_start,),
            )
            client_count = connection.execute(
                f"SELECT COUNT(*) FROM {self.table_name} "  # noqa: S608
                "WHERE client_id = ? AND requested_at >= ?",
                (client_id, window_start),
            ).fetchone()[0]
            if client_count >= self.per_client_limit:
                raise RateLimitExceededError(
                    "per-client rate limit exceeded",
                    retry_after_seconds=self.per_client_window_seconds,
                )
            global_count = connection.execute(
                f"SELECT COUNT(*) FROM {self.table_name} WHERE requested_at >= ?",  # noqa: S608
                (day_start,),
            ).fetchone()[0]
            if global_count >= self.global_daily_limit:
                raise RateLimitExceededError(
                    "daily quota exhausted",
                    retry_after_seconds=86_400,
                )
            connection.execute(
                f"INSERT INTO {self.table_name} (client_id, requested_at) VALUES (?, ?)",  # noqa: S608
                (client_id, now),
            )
