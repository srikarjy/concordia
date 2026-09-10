"""Persist tool executions into the run ledger and evidence graph."""

from __future__ import annotations

import uuid

from concordia.cellforge.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus
from concordia.cellforge.local import LocalExecutionAdapter
from concordia.graph.schema import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphRelation,
)
from concordia.ingestion.service import stable_id
from concordia.runtime.contracts import ArtifactReference, RunStatus
from concordia.runtime.service import RunService


class ToolExecutionService:
    def __init__(self, runs: RunService, adapter: LocalExecutionAdapter):
        self.runs = runs
        self.adapter = adapter

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        record = self.runs.get_run(request.run_id)
        if record.current_status is not RunStatus.EXECUTING:
            raise ValueError("tool execution requires a run in EXECUTING state")
        started_event = self.runs.ledger.append(
            request.run_id,
            "TOOL_EXECUTION_STARTED",
            {"request": request.model_dump(mode="json")},
            expected_sequence=record.last_sequence_number,
        )
        try:
            result = self.adapter.execute(request)
        except Exception as error:
            result = ExecutionResult(
                request_id=request.request_id,
                run_id=request.run_id,
                tool_name=request.tool_name,
                tool_version=request.tool_version,
                status=ExecutionStatus.FAILED,
                error_code="ADAPTER_FAILURE",
                error_message=type(error).__name__,
                elapsed_seconds=0,
                scientific_use_allowed=False,
            )
        result_digest = self.runs.artifacts.put_json(result.model_dump(mode="json"))
        graph = self._provenance_graph(request, result, result_digest, started_event.event_id)
        graph_digest = self.runs.artifacts.put_json(graph.model_dump(mode="json"))
        finished_event_id = str(uuid.uuid4())
        current = self.runs.get_run(request.run_id)
        references = (
            self._reference(
                result_digest,
                finished_event_id,
                f"{request.tool_name}@{request.tool_version}",
            ),
            self._reference(
                graph_digest,
                finished_event_id,
                "cellforge.provenance_graph@1.0.0",
            ),
        )
        self.runs.ledger.append(
            request.run_id,
            "TOOL_EXECUTION_FINISHED",
            {
                "request_id": request.request_id,
                "status": result.status,
                "started_event_id": started_event.event_id,
                "artifacts": [reference.model_dump(mode="json") for reference in references],
            },
            expected_sequence=current.last_sequence_number,
            event_id=finished_event_id,
        )
        return result

    def _reference(
        self, digest: str, event_id: str, producing_tool: str
    ) -> ArtifactReference:
        return ArtifactReference(
            digest=digest,
            media_type="application/json",
            byte_size=len(self.runs.artifacts.get_bytes(digest)),
            schema_version=1,
            producing_event=event_id,
            producing_tool=producing_tool,
            scientific_use_allowed=False,
        )

    @staticmethod
    def _provenance_graph(
        request: ExecutionRequest,
        result: ExecutionResult,
        result_digest: str,
        started_event_id: str,
    ) -> EvidenceGraph:
        tool_node_id = stable_id(
            "toolrun", request.run_id, request.request_id, request.tool_name, request.tool_version
        )
        artifact_node_id = f"artifact:{result_digest}"
        edge_id = stable_id(
            "edge", artifact_node_id, tool_node_id, GraphRelation.WAS_GENERATED_BY
        )
        return EvidenceGraph(
            nodes=(
                GraphNode(
                    node_id=tool_node_id,
                    node_type=GraphNodeType.TOOL_RUN,
                    label=f"{request.tool_name}@{request.tool_version}",
                    properties={
                        "request_id": request.request_id,
                        "run_id": request.run_id,
                        "status": result.status,
                        "started_event_id": started_event_id,
                        "scientific_use_allowed": False,
                    },
                ),
                GraphNode(
                    node_id=artifact_node_id,
                    node_type=GraphNodeType.ARTIFACT,
                    label=result_digest,
                    properties={
                        "artifact_hash": result_digest,
                        "scientific_use_allowed": False,
                    },
                ),
            ),
            edges=(
                GraphEdge(
                    edge_id=edge_id,
                    source=artifact_node_id,
                    target=tool_node_id,
                    relation=GraphRelation.WAS_GENERATED_BY,
                ),
            ),
        )
