"""Application service for the durable genomic fixture vertical slice."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from concordia.events.sqlite import SQLiteEventLedger, request_digest
from concordia.genomics.evo2 import RecordedFixtureScorer
from concordia.genomics.ism import MutationEffect, scan_position
from concordia.genomics.schema import GenomicSequence
from concordia.graph.schema import EvidenceGraph, GraphEdge, GraphNode
from concordia.runtime.contracts import (
    ArtifactReference,
    GenomicFixtureTask,
    ReplayResult,
    RunRecord,
    RunSpec,
    RunStatus,
)
from concordia.runtime.state_machine import reconstruct_run, validate_transition
from concordia.storage.content import ContentAddressedStore
from concordia.verification.backtrack import backtrack_claim


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    protocol_version: str = Field(default="genomic-fixture-v1", min_length=1)
    policy_version: str = Field(default="fixture-deny-scientific-use-v1", min_length=1)
    sequence: GenomicSequence
    scan_position: int = Field(ge=0)


class RunService:
    def __init__(self, ledger: SQLiteEventLedger, artifacts: ContentAddressedStore):
        self.ledger = ledger
        self.artifacts = artifacts

    @classmethod
    def local(cls, root: str | Path) -> RunService:
        root_path = Path(root)
        return cls(
            SQLiteEventLedger(root_path / "events.sqlite3"),
            ContentAddressedStore(root_path / "artifacts"),
        )

    def create_and_execute(self, request: CreateRunRequest) -> RunRecord:
        request_value = request.model_dump(mode="json")
        command_digest = request_digest(request_value)
        existing_run_id = self.ledger.resolve_command(
            request.idempotency_key, command_digest
        )
        if existing_run_id is not None:
            return self.get_run(existing_run_id)
        sequence_payload = self._canonical_bytes(request.sequence.model_dump(mode="json"))
        sequence_digest = self.artifacts.put_bytes(sequence_payload)
        run_id = str(uuid.uuid4())
        created_event_id = str(uuid.uuid4())
        spec = RunSpec(
            run_id=run_id,
            idempotency_key=request.idempotency_key,
            protocol_version=request.protocol_version,
            policy_version=request.policy_version,
            input_artifact_ids=(sequence_digest,),
            task=GenomicFixtureTask(
                sequence_artifact_id=sequence_digest,
                scan_position=request.scan_position,
            ),
        )
        input_reference = self._reference(
            sequence_digest,
            event_id=created_event_id,
            producing_tool="api.create_run",
        )
        persisted_run_id = self.ledger.create_run(
            run_id=run_id,
            idempotency_key=request.idempotency_key,
            command_digest=command_digest,
            event_id=created_event_id,
            payload={"spec": spec.model_dump(mode="json"), "artifacts": [input_reference]},
        )
        if persisted_run_id != run_id:
            return self.get_run(persisted_run_id)
        try:
            return self._execute(spec, request.sequence)
        except ValueError as error:
            self.transition(run_id, RunStatus.FAILED_VALIDATION, reason=str(error))
            return self.get_run(run_id)
        except Exception as error:
            self.transition(run_id, RunStatus.FAILED_TOOL, reason=type(error).__name__)
            raise

    def _execute(self, spec: RunSpec, sequence: GenomicSequence) -> RunRecord:
        run_id = spec.run_id
        for status in (
            RunStatus.VALIDATING,
            RunStatus.INGESTING,
            RunStatus.GRAPH_READY,
            RunStatus.PLANNING,
            RunStatus.SCHEDULED,
            RunStatus.EXECUTING,
        ):
            self.transition(run_id, status)

        if spec.task.scan_position >= len(sequence.sequence):
            raise ValueError("scan position exceeds sequence length")
        scorer = RecordedFixtureScorer()
        score = scorer.score(sequence)
        effects = scan_position(sequence, spec.task.scan_position, scorer)
        score_digest = self.artifacts.put_json(score.model_dump(mode="json"))
        effects_digest = self.artifacts.put_json(
            [effect.model_dump(mode="json") for effect in effects]
        )
        execution_event_id = str(uuid.uuid4())
        record = self.get_run(run_id)
        self.ledger.append(
            run_id,
            "FIXTURE_STAGE_COMPLETED",
            {
                "execution_mode": "recorded_fixture",
                "scientific_use_allowed": False,
                "artifacts": [
                    self._reference(
                        score_digest,
                        event_id=execution_event_id,
                        producing_tool="evo2.recorded_fixture.score",
                    ),
                    self._reference(
                        effects_digest,
                        event_id=execution_event_id,
                        producing_tool="xai.mutational_scan",
                    ),
                ],
            },
            expected_sequence=record.last_sequence_number,
            event_id=execution_event_id,
        )
        self.transition(run_id, RunStatus.CLAIM_VALIDATION)

        strongest = max(effects, key=lambda effect: abs(effect.delta))
        graph = self._fixture_graph(spec, scorer.model_id, score_digest, effects_digest, strongest)
        graph_digest = self.artifacts.put_json(graph.model_dump(mode="json"))
        graph_event_id = str(uuid.uuid4())
        record = self.get_run(run_id)
        self.ledger.append(
            run_id,
            "EVIDENCE_GRAPH_PERSISTED",
            {
                "artifacts": [
                    self._reference(
                        graph_digest,
                        event_id=graph_event_id,
                        producing_tool="graph.fixture_builder",
                    )
                ]
            },
            expected_sequence=record.last_sequence_number,
            event_id=graph_event_id,
        )
        self.transition(run_id, RunStatus.BACKTRACKING)
        verification = backtrack_claim(
            graph, "claim:fixture-1", f"sequence:{spec.task.sequence_artifact_id}"
        )
        verification_digest = self.artifacts.put_json(verification.model_dump(mode="json"))
        verification_event_id = str(uuid.uuid4())
        record = self.get_run(run_id)
        self.ledger.append(
            run_id,
            "CLAIM_BACKTRACKED",
            {
                "verification_status": verification.status,
                "artifacts": [
                    self._reference(
                        verification_digest,
                        event_id=verification_event_id,
                        producing_tool="lineage.backtrack",
                    )
                ],
            },
            expected_sequence=record.last_sequence_number,
            event_id=verification_event_id,
        )
        for status in (RunStatus.EVALUATING, RunStatus.REPORTING, RunStatus.COMPLETED):
            self.transition(run_id, status)
        return self.get_run(run_id)

    def transition(
        self, run_id: str, requested: RunStatus, *, reason: str | None = None
    ) -> RunRecord:
        record = self.get_run(run_id)
        validate_transition(record.current_status, requested)
        payload: dict[str, Any] = {
            "from_status": record.current_status,
            "to_status": requested,
        }
        if reason is not None:
            payload["reason"] = reason
        self.ledger.append(
            run_id,
            "STATE_TRANSITIONED",
            payload,
            expected_sequence=record.last_sequence_number,
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RunRecord:
        return reconstruct_run(self.ledger.all_events(run_id))

    def replay(self, run_id: str) -> ReplayResult:
        events = self.ledger.all_events(run_id)
        return ReplayResult(run=reconstruct_run(events), event_count=len(events))

    def artifact_references(self, run_id: str) -> tuple[ArtifactReference, ...]:
        references = []
        for event in self.ledger.all_events(run_id):
            for value in event.payload.get("artifacts", []):
                reference = ArtifactReference.model_validate(value)
                self.artifacts.get_bytes(reference.digest)
                references.append(reference)
        return tuple(references)

    def _reference(
        self, digest: str, *, event_id: str, producing_tool: str
    ) -> dict[str, Any]:
        reference = ArtifactReference(
            digest=digest,
            media_type="application/json",
            byte_size=len(self.artifacts.get_bytes(digest)),
            schema_version=1,
            producing_event=event_id,
            producing_tool=producing_tool,
            scientific_use_allowed=False,
        )
        return reference.model_dump(mode="json")

    @staticmethod
    def _canonical_bytes(value: Any) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")

    @staticmethod
    def _fixture_graph(
        spec: RunSpec,
        model_id: str,
        score_digest: str,
        effects_digest: str,
        strongest: MutationEffect,
    ) -> EvidenceGraph:
        fixture_properties = {"scientific_use_allowed": False}
        return EvidenceGraph(
            nodes=(
                GraphNode(
                    node_id="claim:fixture-1",
                    node_type="ScientificClaim",
                    label="Fixture score changes after one substitution",
                    properties=fixture_properties,
                ),
                GraphNode(
                    node_id=f"effect:{effects_digest}",
                    node_type="CounterfactualEffect",
                    label=(
                        f"Position {strongest.position} "
                        f"{strongest.reference}>{strongest.alternate}"
                    ),
                    properties={**fixture_properties, "artifact_hash": effects_digest},
                ),
                GraphNode(
                    node_id=f"score:{score_digest}",
                    node_type="ModelOutput",
                    label=model_id,
                    properties={**fixture_properties, "artifact_hash": score_digest},
                ),
                GraphNode(
                    node_id=f"sequence:{spec.task.sequence_artifact_id}",
                    node_type="GenomicSequence",
                    label="persisted genomic input",
                    properties={
                        **fixture_properties,
                        "artifact_hash": spec.task.sequence_artifact_id,
                    },
                ),
            ),
            edges=(
                GraphEdge(
                    edge_id="edge:claim-effect",
                    source="claim:fixture-1",
                    target=f"effect:{effects_digest}",
                    relation="supported_by",
                ),
                GraphEdge(
                    edge_id="edge:effect-score",
                    source=f"effect:{effects_digest}",
                    target=f"score:{score_digest}",
                    relation="derived_from",
                ),
                GraphEdge(
                    edge_id="edge:score-sequence",
                    source=f"score:{score_digest}",
                    target=f"sequence:{spec.task.sequence_artifact_id}",
                    relation="used",
                ),
            ),
        )
