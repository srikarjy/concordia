"""Append-only SQLite event ledger with optimistic concurrency and a hash chain.

Every event stores ``prev_hash`` and ``event_hash``, where ``event_hash`` is the
SHA-256 of the canonical event record including ``prev_hash``. Each run is its
own chain, starting from ``GENESIS``. Editing, deleting or reordering any stored
event breaks the chain at that event, which ``verify_chain`` reports.

The chain makes tampering detectable, not impossible: someone with write access
can rewrite a whole chain consistently. ``ledger_root`` gives one digest over
every run's head, so publishing it somewhere outside this database (a git
commit, for instance) pins the history as of that moment.

Events written before the chain existed are hashed when migration 3 runs
(version 2 belongs to the job queue), so the chain proves integrity only from
that migration onward; the migration's time is recorded in ``schema_migrations``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from concordia.runtime.contracts import EventPage, RunEvent

GENESIS = "0" * 64


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


def event_hash(row: dict[str, Any], prev_hash: str) -> str:
    """Hash one stored event; ``payload_json`` is hashed exactly as stored."""

    record = {
        "prev_hash": prev_hash,
        "run_id": row["run_id"],
        "sequence_number": row["sequence_number"],
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "schema_version": row["schema_version"],
        "created_at": row["created_at"],
        "payload_json": row["payload_json"],
    }
    return request_digest(record)


def merkle_root(leaves: list[str]) -> str:
    """Binary SHA-256 Merkle root; an odd node is paired with itself."""

    if not leaves:
        return GENESIS
    level = [hashlib.sha256(leaf.encode("utf-8")).hexdigest() for leaf in leaves]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256((level[i] + level[i + 1]).encode("utf-8")).hexdigest()
            for i in range(0, len(level), 2)
        ]
    return level[0]


class ChainBreak(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    sequence_number: int
    reason: str


class ChainReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs_checked: int
    events_checked: int
    heads: dict[str, str]
    breaks: tuple[ChainBreak, ...]

    @property
    def intact(self) -> bool:
        return not self.breaks


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
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 3"
            ).fetchone()
            if applied is None:
                self._migrate_hash_chain(connection)

    @staticmethod
    def _migrate_hash_chain(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
        if "prev_hash" not in columns:
            connection.execute("ALTER TABLE events ADD COLUMN prev_hash TEXT")
            connection.execute("ALTER TABLE events ADD COLUMN event_hash TEXT")
        rows = connection.execute(
            "SELECT * FROM events ORDER BY run_id, sequence_number"
        ).fetchall()
        previous: dict[str, str] = {}
        for row in rows:
            prev = previous.get(row["run_id"], GENESIS)
            digest = event_hash(dict(row), prev)
            connection.execute(
                "UPDATE events SET prev_hash = ?, event_hash = ? "
                "WHERE run_id = ? AND sequence_number = ?",
                (prev, digest, row["run_id"], row["sequence_number"]),
            )
            previous[row["run_id"]] = digest
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (3, ?)",
            (datetime.now(UTC).isoformat(),),
        )
        connection.commit()

    def _insert_event(self, connection: sqlite3.Connection, row: dict[str, Any]) -> None:
        if row["sequence_number"] == 1:
            prev = GENESIS
        else:
            found = connection.execute(
                "SELECT event_hash FROM events WHERE run_id = ? AND sequence_number = ?",
                (row["run_id"], row["sequence_number"] - 1),
            ).fetchone()
            prev = found["event_hash"]
        connection.execute(
            """INSERT INTO events
               (run_id, sequence_number, event_id, event_type, schema_version,
                created_at, payload_json, prev_hash, event_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["run_id"],
                row["sequence_number"],
                row["event_id"],
                row["event_type"],
                row["schema_version"],
                row["created_at"],
                row["payload_json"],
                prev,
                event_hash(row, prev),
            ),
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
            self._insert_event(
                connection,
                {
                    "run_id": run_id,
                    "sequence_number": 1,
                    "event_id": event_id,
                    "event_type": "RUN_CREATED",
                    "schema_version": 1,
                    "created_at": now,
                    "payload_json": canonical_json(payload),
                },
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
            self._insert_event(
                connection,
                {
                    "run_id": run_id,
                    "sequence_number": sequence_number,
                    "event_id": event_id,
                    "event_type": event_type,
                    "schema_version": 1,
                    "created_at": created_at.isoformat(),
                    "payload_json": canonical_json(payload),
                },
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

    def verify_chain(self, run_id: str | None = None) -> ChainReport:
        """Recompute every hash and report the first break in each run."""

        query = "SELECT * FROM events"
        params: tuple[str, ...] = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            params = (run_id,)
        with self._connect() as connection:
            rows = connection.execute(
                query + " ORDER BY run_id, sequence_number", params
            ).fetchall()
        heads: dict[str, str] = {}
        broken: dict[str, ChainBreak] = {}
        expected_sequence: dict[str, int] = {}
        for row in rows:
            run = row["run_id"]
            if run in broken:
                continue
            sequence = row["sequence_number"]
            expected = expected_sequence.get(run, 1)
            prev = heads.get(run, GENESIS)
            reason = None
            if sequence != expected:
                reason = f"expected sequence {expected}, found {sequence}"
            elif row["prev_hash"] != prev:
                reason = "prev_hash does not match the preceding event"
            elif row["event_hash"] != event_hash(dict(row), prev):
                reason = "event content does not match its hash"
            if reason is not None:
                broken[run] = ChainBreak(run_id=run, sequence_number=sequence, reason=reason)
                continue
            heads[run] = row["event_hash"]
            expected_sequence[run] = sequence + 1
        return ChainReport(
            runs_checked=len({row["run_id"] for row in rows}),
            events_checked=len(rows),
            heads={run: head for run, head in sorted(heads.items()) if run not in broken},
            breaks=tuple(broken[run] for run in sorted(broken)),
        )

    def ledger_root(self) -> str:
        """One digest over every run's current head, for publishing outside the ledger."""

        report = self.verify_chain()
        if not report.intact:
            raise ValueError("ledger chain is broken; refusing to compute a root")
        return merkle_root([f"{run}:{head}" for run, head in report.heads.items()])

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
