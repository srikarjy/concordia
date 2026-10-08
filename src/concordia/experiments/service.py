"""SQLite-backed immutable experiment DAG and content-addressed payloads."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path

from concordia.experiments.schema import (
    CreateExperimentNodeRequest,
    CreateExperimentRequest,
    CreateExperimentResponse,
    ExperimentComparison,
    ExperimentEdge,
    ExperimentManifest,
    ExperimentNode,
    ExperimentNodeKind,
    ExperimentOperation,
    ExperimentPayload,
    ExperimentRecord,
    MeasurementPayload,
    manifest_digest,
    utc_now,
)
from concordia.storage.content import ContentAddressedStore


class ExperimentNotFoundError(LookupError):
    pass


class ExperimentAccessError(PermissionError):
    pass


class ExperimentNodeNotFoundError(LookupError):
    pass


class ExperimentConflictError(RuntimeError):
    pass


class ExperimentStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "experiments.sqlite3"
        self.artifacts = ContentAddressedStore(self.root / "artifacts")
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    access_token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_nodes (
                    node_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    node_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_edges (
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    parent_id TEXT NOT NULL REFERENCES experiment_nodes(node_id),
                    child_id TEXT NOT NULL REFERENCES experiment_nodes(node_id),
                    PRIMARY KEY (parent_id, child_id)
                );
                CREATE TABLE IF NOT EXISTS selected_candidates (
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    node_id TEXT NOT NULL REFERENCES experiment_nodes(node_id),
                    selected_at TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, node_id)
                );
                CREATE INDEX IF NOT EXISTS idx_experiment_nodes_experiment
                    ON experiment_nodes(experiment_id, created_at, node_id);
                """
            )

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self, request: CreateExperimentRequest) -> CreateExperimentResponse:
        experiment_id = str(uuid.uuid4())
        access_token = secrets.token_urlsafe(32)
        record = ExperimentRecord(
            experiment_id=experiment_id,
            title=request.title,
            description=request.description,
            created_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO experiments "
                "(experiment_id, title, description, access_token_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.experiment_id,
                    record.title,
                    record.description,
                    self._token_hash(access_token),
                    record.created_at.isoformat(),
                ),
            )
        return CreateExperimentResponse(experiment=record, access_token=access_token)

    def authorize(self, experiment_id: str, access_token: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT access_token_hash FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise ExperimentNotFoundError(experiment_id)
        if not secrets.compare_digest(row["access_token_hash"], self._token_hash(access_token)):
            raise ExperimentAccessError(experiment_id)

    def add_node(
        self, experiment_id: str, request: CreateExperimentNodeRequest
    ) -> ExperimentNode:
        artifact_digest = self.artifacts.put_json(request.payload.model_dump(mode="json"))
        node = ExperimentNode(
            node_id=str(uuid.uuid4()),
            experiment_id=experiment_id,
            kind=request.kind,
            operation=request.operation,
            label=request.label,
            branch=request.branch,
            parent_ids=request.parent_ids,
            artifact_digest=artifact_digest,
            mutations=request.mutations,
            evidence_artifact_digests=request.evidence_artifact_digests,
            scientific_use_allowed=request.scientific_use_allowed,
            created_at=utc_now(),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone() is None:
                raise ExperimentNotFoundError(experiment_id)
            if request.parent_ids:
                placeholders = ",".join("?" for _ in request.parent_ids)
                rows = connection.execute(
                    f"SELECT node_id FROM experiment_nodes "  # noqa: S608 - placeholders only
                    f"WHERE experiment_id = ? AND node_id IN ({placeholders})",
                    (experiment_id, *request.parent_ids),
                ).fetchall()
                if {row["node_id"] for row in rows} != set(request.parent_ids):
                    raise ExperimentConflictError("every parent must belong to this experiment")
            connection.execute(
                "INSERT INTO experiment_nodes (node_id, experiment_id, node_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    node.node_id,
                    experiment_id,
                    node.model_dump_json(),
                    node.created_at.isoformat(),
                ),
            )
            connection.executemany(
                "INSERT INTO experiment_edges (experiment_id, parent_id, child_id) "
                "VALUES (?, ?, ?)",
                [(experiment_id, parent_id, node.node_id) for parent_id in request.parent_ids],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return node

    def record_model_operation(
        self,
        experiment_id: str,
        *,
        parent_node_id: str,
        branch: str,
        run_label: str,
        run_payload: ExperimentPayload,
        output_label: str,
        output_kind: ExperimentNodeKind,
        output_payload: ExperimentPayload,
        operation: ExperimentOperation,
        evidence_artifact_digests: tuple[str, ...] = (),
        scientific_use_allowed: bool = False,
    ) -> tuple[ExperimentNode, ExperimentNode]:
        """Atomically attach one model run and its output to an existing parent.

        Payload bytes are content-addressed before the SQLite transaction. A failed
        transaction can leave unreachable immutable blobs, but it can never expose a
        partial lineage containing only the run or only the output.
        """

        if run_payload.payload_type != "model_run":
            raise ExperimentConflictError("run payload must have type model_run")
        expected_output_kind = {
            "dna": ExperimentNodeKind.DNA_SEQUENCE,
            "protein": ExperimentNodeKind.PROTEIN_SEQUENCE,
            "structure": ExperimentNodeKind.STRUCTURE,
            "measurement": ExperimentNodeKind.MEASUREMENT,
            "evidence": ExperimentNodeKind.EVIDENCE,
        }.get(output_payload.payload_type)
        if expected_output_kind != output_kind:
            raise ExperimentConflictError("output payload type does not match output kind")

        run_digest = self.artifacts.put_json(run_payload.model_dump(mode="json"))
        output_digest = self.artifacts.put_json(output_payload.model_dump(mode="json"))
        created_at = utc_now()
        run_node = ExperimentNode(
            node_id=str(uuid.uuid4()),
            experiment_id=experiment_id,
            kind=ExperimentNodeKind.MODEL_RUN,
            operation=operation,
            label=run_label,
            branch=branch,
            parent_ids=(parent_node_id,),
            artifact_digest=run_digest,
            mutations=(),
            evidence_artifact_digests=evidence_artifact_digests,
            scientific_use_allowed=scientific_use_allowed,
            created_at=created_at,
        )
        output_node = ExperimentNode(
            node_id=str(uuid.uuid4()),
            experiment_id=experiment_id,
            kind=output_kind,
            operation=operation,
            label=output_label,
            branch=branch,
            parent_ids=(run_node.node_id,),
            artifact_digest=output_digest,
            mutations=(),
            evidence_artifact_digests=evidence_artifact_digests,
            scientific_use_allowed=scientific_use_allowed,
            created_at=created_at + timedelta(microseconds=1),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            parent = connection.execute(
                "SELECT 1 FROM experiment_nodes WHERE experiment_id = ? AND node_id = ?",
                (experiment_id, parent_node_id),
            ).fetchone()
            if parent is None:
                raise ExperimentNodeNotFoundError(parent_node_id)
            for node in (run_node, output_node):
                connection.execute(
                    "INSERT INTO experiment_nodes "
                    "(node_id, experiment_id, node_json, created_at) VALUES (?, ?, ?, ?)",
                    (
                        node.node_id,
                        experiment_id,
                        node.model_dump_json(),
                        node.created_at.isoformat(),
                    ),
                )
            connection.executemany(
                "INSERT INTO experiment_edges (experiment_id, parent_id, child_id) "
                "VALUES (?, ?, ?)",
                (
                    (experiment_id, parent_node_id, run_node.node_id),
                    (experiment_id, run_node.node_id, output_node.node_id),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return run_node, output_node

    def _experiment(self, experiment_id: str) -> ExperimentRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT experiment_id, title, description, created_at FROM experiments "
                "WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise ExperimentNotFoundError(experiment_id)
        return ExperimentRecord.model_validate(dict(row))

    def _nodes(self, experiment_id: str) -> tuple[ExperimentNode, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT node_json FROM experiment_nodes WHERE experiment_id = ? "
                "ORDER BY created_at, node_id",
                (experiment_id,),
            ).fetchall()
        return tuple(ExperimentNode.model_validate_json(row["node_json"]) for row in rows)

    def manifest(self, experiment_id: str) -> ExperimentManifest:
        experiment = self._experiment(experiment_id)
        nodes = self._nodes(experiment_id)
        with self._connect() as connection:
            edge_rows = connection.execute(
                "SELECT parent_id, child_id FROM experiment_edges WHERE experiment_id = ? "
                "ORDER BY parent_id, child_id",
                (experiment_id,),
            ).fetchall()
            selected_rows = connection.execute(
                "SELECT node_id FROM selected_candidates WHERE experiment_id = ? "
                "ORDER BY selected_at, node_id",
                (experiment_id,),
            ).fetchall()
        edges = tuple(ExperimentEdge.model_validate(dict(row)) for row in edge_rows)
        selected = tuple(row["node_id"] for row in selected_rows)
        content = {
            "schema_version": 1,
            "experiment": experiment.model_dump(mode="json"),
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": [edge.model_dump(mode="json") for edge in edges],
            "selected_candidate_ids": selected,
        }
        return ExperimentManifest(
            experiment=experiment,
            nodes=nodes,
            edges=edges,
            selected_candidate_ids=selected,
            manifest_digest=manifest_digest(content),
        )

    def select(self, experiment_id: str, node_id: str) -> ExperimentManifest:
        now = utc_now().isoformat()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM experiment_nodes WHERE experiment_id = ? AND node_id = ?",
                (experiment_id, node_id),
            ).fetchone()
            if exists is None:
                raise ExperimentNodeNotFoundError(node_id)
            connection.execute(
                "INSERT OR IGNORE INTO selected_candidates "
                "(experiment_id, node_id, selected_at) VALUES (?, ?, ?)",
                (experiment_id, node_id, now),
            )
        return self.manifest(experiment_id)

    def payload(self, experiment_id: str, node_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT node_json FROM experiment_nodes "
                "WHERE experiment_id = ? AND node_id = ?",
                (experiment_id, node_id),
            ).fetchone()
        if row is None:
            raise ExperimentNodeNotFoundError(node_id)
        node = ExperimentNode.model_validate_json(row["node_json"])
        value = json.loads(self.artifacts.get_bytes(node.artifact_digest))
        if not isinstance(value, dict):
            raise ExperimentConflictError("experiment payload is not a JSON object")
        return value

    def compare(self, experiment_id: str, left_id: str, right_id: str) -> ExperimentComparison:
        nodes = {node.node_id: node for node in self._nodes(experiment_id)}
        if left_id not in nodes or right_id not in nodes:
            raise ExperimentNodeNotFoundError("comparison node not found")
        left = nodes[left_id]
        right = nodes[right_id]
        if left.kind != right.kind:
            return ExperimentComparison(
                left_node_id=left_id,
                right_node_id=right_id,
                comparable=False,
                kind=None,
                reasons=("nodes have different molecular kinds",),
            )
        left_payload = json.loads(self.artifacts.get_bytes(left.artifact_digest))
        right_payload = json.loads(self.artifacts.get_bytes(right.artifact_digest))
        if left.kind in {
            ExperimentNodeKind.DNA_SEQUENCE,
            ExperimentNodeKind.PROTEIN_SEQUENCE,
        }:
            left_sequence = str(left_payload["sequence"])
            right_sequence = str(right_payload["sequence"])
            differing = tuple(
                index
                for index, (a, b) in enumerate(zip(left_sequence, right_sequence, strict=False))
                if a != b
            )
            return ExperimentComparison(
                left_node_id=left_id,
                right_node_id=right_id,
                comparable=True,
                kind=left.kind,
                length_delta=len(right_sequence) - len(left_sequence),
                differing_positions=differing,
            )
        if left.kind == ExperimentNodeKind.MEASUREMENT:
            left_measurement = MeasurementPayload.model_validate(left_payload)
            right_measurement = MeasurementPayload.model_validate(right_payload)
            if left_measurement.metric != right_measurement.metric:
                return ExperimentComparison(
                    left_node_id=left_id,
                    right_node_id=right_id,
                    comparable=False,
                    kind=left.kind,
                    reasons=("measurements use different metrics",),
                )
            return ExperimentComparison(
                left_node_id=left_id,
                right_node_id=right_id,
                comparable=True,
                kind=left.kind,
                value_delta=right_measurement.value - left_measurement.value,
            )
        return ExperimentComparison(
            left_node_id=left_id,
            right_node_id=right_id,
            comparable=False,
            kind=left.kind,
            reasons=("this node kind has no deterministic comparison yet",),
        )
