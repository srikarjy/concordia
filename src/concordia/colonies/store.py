"""Append-only SQLite event storage for colony state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from concordia.colonies.schema import ColonyEvent


class ColonyNotFoundError(LookupError):
    pass


class ColonyConcurrencyError(RuntimeError):
    pass


class ColonyIdempotencyConflict(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SQLiteColonyLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS colony_events (
                    colony_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (colony_id, sequence_number)
                );
                CREATE TABLE IF NOT EXISTS colony_commands (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    colony_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def create(
        self,
        colony_id: str,
        idempotency_key: str,
        request_digest: str,
        payload: dict[str, Any],
    ) -> str:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT request_digest, colony_id FROM colony_commands WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_digest:
                    connection.rollback()
                    raise ColonyIdempotencyConflict(idempotency_key)
                connection.commit()
                return str(existing["colony_id"])
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO colony_events VALUES (?,1,?,'COLONY_CREATED',?,?)",
                (colony_id, str(uuid.uuid4()), now, canonical_json(payload)),
            )
            connection.execute(
                "INSERT INTO colony_commands VALUES (?,?,?,?)",
                (idempotency_key, request_digest, colony_id, now),
            )
            connection.commit()
        return colony_id

    def append(
        self,
        colony_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        expected_sequence: int,
    ) -> ColonyEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT COALESCE(MAX(sequence_number),0) current
                   FROM colony_events WHERE colony_id=?""",
                (colony_id,),
            ).fetchone()
            current = int(row["current"])
            if current == 0:
                connection.rollback()
                raise ColonyNotFoundError(colony_id)
            if current != expected_sequence:
                connection.rollback()
                raise ColonyConcurrencyError(
                    f"expected colony sequence {expected_sequence}, found {current}"
                )
            created_at = datetime.now(UTC)
            event = ColonyEvent(
                event_id=str(uuid.uuid4()),
                colony_id=colony_id,
                sequence_number=current + 1,
                event_type=event_type,
                created_at=created_at,
                payload=payload,
            )
            connection.execute(
                "INSERT INTO colony_events VALUES (?,?,?,?,?,?)",
                (
                    colony_id,
                    event.sequence_number,
                    event.event_id,
                    event_type,
                    created_at.isoformat(),
                    canonical_json(payload),
                ),
            )
            connection.commit()
        return event

    def events(self, colony_id: str) -> tuple[ColonyEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM colony_events WHERE colony_id=? ORDER BY sequence_number",
                (colony_id,),
            ).fetchall()
        if not rows:
            raise ColonyNotFoundError(colony_id)
        return tuple(
            ColonyEvent(
                event_id=row["event_id"],
                colony_id=row["colony_id"],
                sequence_number=row["sequence_number"],
                event_type=row["event_type"],
                created_at=datetime.fromisoformat(row["created_at"]),
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        )
