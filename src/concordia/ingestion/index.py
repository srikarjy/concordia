"""Append-only source revision index for project ingestion."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SourceRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_id: str
    revision_number: int = Field(ge=1)


class IngestionIndex:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS ingestion_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_revisions (
                    relative_path TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    node_id TEXT NOT NULL UNIQUE,
                    revision_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (relative_path, digest),
                    UNIQUE (relative_path, revision_number)
                );
                INSERT OR IGNORE INTO ingestion_schema_migrations(version, applied_at)
                VALUES (1, CURRENT_TIMESTAMP);
                """
            )

    def record(self, relative_path: str, digest: str, node_id: str) -> SourceRevision:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT * FROM source_revisions
                   WHERE relative_path = ? AND digest = ?""",
                (relative_path, digest),
            ).fetchone()
            if existing is None:
                latest = connection.execute(
                    """SELECT COALESCE(MAX(revision_number), 0) AS latest
                       FROM source_revisions WHERE relative_path = ?""",
                    (relative_path,),
                ).fetchone()
                revision_number = int(latest["latest"]) + 1
                connection.execute(
                    """INSERT INTO source_revisions
                       (relative_path, digest, node_id, revision_number, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        relative_path,
                        digest,
                        node_id,
                        revision_number,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                connection.commit()
                return SourceRevision(
                    relative_path=relative_path,
                    digest=digest,
                    node_id=node_id,
                    revision_number=revision_number,
                )
            connection.commit()
        return self._row(existing)

    def revisions(self, relative_path: str) -> tuple[SourceRevision, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM source_revisions WHERE relative_path = ?
                   ORDER BY revision_number""",
                (relative_path,),
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    @staticmethod
    def _row(row: sqlite3.Row) -> SourceRevision:
        return SourceRevision(
            relative_path=row["relative_path"],
            digest=row["digest"],
            node_id=row["node_id"],
            revision_number=row["revision_number"],
        )
