"""Append-only SQLite event ledger with optimistic concurrency."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from concordia.runtime.contracts import EventPage, RunEvent


class ConcurrencyError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


class RunNotFoundError(LookupError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def request_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class SQLiteEventLedger:
    """SQLite persistence whose authoritative run history is the events table."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence_number)
                );
                CREATE TABLE IF NOT EXISTS commands (
                    idempotency_key TEXT PRIMARY KEY,
                    command_name TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                VALUES (1, CURRENT_TIMESTAMP);
                """
            )

    def create_run(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        command_digest: str,
        payload: dict[str, Any],
        event_id: str,
    ) -> str:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT request_digest, run_id FROM commands WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != command_digest:
                    connection.rollback()
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different request"
                    )
                connection.commit()
                return str(existing["run_id"])
            now = datetime.now(UTC).isoformat()
            connection.execute(
                """INSERT INTO events
                   (run_id, sequence_number, event_id, event_type, schema_version,
                    created_at, payload_json)
                   VALUES (?, 1, ?, 'RUN_CREATED', 1, ?, ?)""",
                (run_id, event_id, now, canonical_json(payload)),
            )
            connection.execute(
                """INSERT INTO commands
                   (idempotency_key, command_name, request_digest, run_id, created_at)
                   VALUES (?, 'CREATE', ?, ?, ?)""",
                (idempotency_key, command_digest, run_id, now),
            )
            connection.commit()
        return run_id

    def resolve_command(self, idempotency_key: str, command_digest: str) -> str | None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT request_digest, run_id FROM commands WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if existing is None:
            return None
        if existing["request_digest"] != command_digest:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different request"
            )
        return str(existing["run_id"])

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        expected_sequence: int,
        event_id: str | None = None,
    ) -> RunEvent:
        event_id = event_id or str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) AS current FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            current = int(row["current"])
            if current == 0:
                connection.rollback()
                raise RunNotFoundError(run_id)
            if current != expected_sequence:
                connection.rollback()
                raise ConcurrencyError(
                    f"expected run sequence {expected_sequence}, found {current}"
                )
            sequence_number = current + 1
            created_at = datetime.now(UTC)
            connection.execute(
                """INSERT INTO events
                   (run_id, sequence_number, event_id, event_type, schema_version,
                    created_at, payload_json)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (
                    run_id,
                    sequence_number,
                    event_id,
                    event_type,
                    created_at.isoformat(),
                    canonical_json(payload),
                ),
            )
            connection.commit()
        return RunEvent(
            event_id=event_id,
            run_id=run_id,
            sequence_number=sequence_number,
            event_type=event_type,
            created_at=created_at,
            payload=payload,
        )

    def events(self, run_id: str, *, after: int = 0, limit: int = 100) -> EventPage:
        if limit < 1 or limit > 500:
            raise ValueError("event page limit must be between 1 and 500")
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM events WHERE run_id = ? AND sequence_number > ?
                   ORDER BY sequence_number LIMIT ?""",
                (run_id, after, limit + 1),
            ).fetchall()
            exists = connection.execute(
                "SELECT 1 FROM events WHERE run_id = ? LIMIT 1", (run_id,)
            ).fetchone()
        if exists is None:
            raise RunNotFoundError(run_id)
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(self._row_to_event(row) for row in selected)
        next_cursor = items[-1].sequence_number if has_more else None
        return EventPage(items=items, next_cursor=next_cursor)

    def all_events(self, run_id: str) -> tuple[RunEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY sequence_number", (run_id,)
            ).fetchall()
        if not rows:
            raise RunNotFoundError(run_id)
        return tuple(self._row_to_event(row) for row in rows)

    def run_ids(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT run_id FROM events ORDER BY run_id"
            ).fetchall()
        return tuple(str(row["run_id"]) for row in rows)

    def ping(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> RunEvent:
        return RunEvent(
            schema_version=row["schema_version"],
            event_id=row["event_id"],
            run_id=row["run_id"],
            sequence_number=row["sequence_number"],
            event_type=row["event_type"],
            created_at=datetime.fromisoformat(row["created_at"]),
            payload=json.loads(row["payload_json"]),
        )
