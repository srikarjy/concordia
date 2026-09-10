"""Bounded, artifact-preserving runtime for one isolated genomic scientist."""

from __future__ import annotations

import json
import uuid
from typing import Protocol

from pydantic import ValidationError

from concordia.cellforge.contracts import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ResourceBudget,
    SandboxPolicy,
)
from concordia.graph.schema import EvidenceGraph
from concordia.scientist.adapters import ScientistModelAdapter
from concordia.scientist.contracts import (
    SCIENTIST_TURN_ADAPTER,
    FinalScientificResponse,
    GenomicScientistTask,
    GraphQueryRequest,
    ScientistExecutionRecord,
    ScientistExecutionStatus,
    ScientistTurnRecord,
    ToolRequest,
    VerificationRequest,
)
from concordia.scientist.genomic_prompt import (
    GENOMIC_PROMPT_VERSION,
    render_genomic_messages,
)
from concordia.storage.content import ContentAddressedStore


class ScientificToolExecutor(Protocol):
    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...


class SeedScientistRuntime:
    def __init__(
        self,
        adapter: ScientistModelAdapter,
        tools: ScientificToolExecutor,
        artifacts: ContentAddressedStore,
        policy: SandboxPolicy,
        *,
        max_turns: int = 4,
        budget: ResourceBudget | None = None,
    ):
        if max_turns < 1 or max_turns > 20:
            raise ValueError("max_turns must be between 1 and 20")
        self.adapter = adapter
        self.tools = tools
        self.artifacts = artifacts
        self.policy = policy
        self.max_turns = max_turns
        self.budget = budget or ResourceBudget()

    def run(
        self,
        task: GenomicScientistTask,
        run_id: str,
        *,
        execution_id: str | None = None,
    ) -> ScientistExecutionRecord:
        identity = execution_id or str(uuid.uuid4())
        messages = render_genomic_messages(task)
        task_digest = self.artifacts.put_json(task.model_dump(mode="json"))
        prompt_digest = self.artifacts.put_json(
            {
                "prompt_version": GENOMIC_PROMPT_VERSION,
                "messages": messages,
                "response_schema": SCIENTIST_TURN_ADAPTER.json_schema(),
            }
        )
        records: list[ScientistTurnRecord] = []
        final: FinalScientificResponse | None = None
        status = ScientistExecutionStatus.LIMIT_EXCEEDED
        terminal_reason: str | None = "scientist turn budget exhausted"
        reference_errors: tuple[str, ...] = ()
        checkpoint_digest = None
        identity_error = None
        try:
            checkpoint_digest = self.adapter.checkpoint_digest
            graph = EvidenceGraph.model_validate_json(
                self.artifacts.get_bytes(task.graph_artifact_digest)
            )
            if not set(task.evidence_node_ids).issubset({node.node_id for node in graph.nodes}):
                raise ValueError("task contains evidence nodes absent from its frozen graph")
        except Exception as error:
            identity_error = error

        for turn_number in range(1, self.max_turns + 1):
            request_digest = self.artifacts.put_json(
                {
                    "execution_id": identity,
                    "turn_number": turn_number,
                    "model_identity": self.adapter.model_identity,
                    "checkpoint_digest": checkpoint_digest,
                    "model_settings": self.adapter.request_settings,
                    "policy": self.policy.model_dump(mode="json"),
                    "max_turns": self.max_turns,
                    "budget": self.budget.model_dump(mode="json"),
                    "messages": messages,
                    "response_schema": SCIENTIST_TURN_ADAPTER.json_schema(),
                }
            )
            try:
                if identity_error is not None:
                    raise identity_error
                model_response = self.adapter.generate(
                    messages, SCIENTIST_TURN_ADAPTER.json_schema()
                )
            except Exception as error:
                records.append(
                    ScientistTurnRecord(
                        turn_number=turn_number,
                        request_artifact_digest=request_digest,
                        validation_error=f"{type(error).__name__}: {error}",
                    )
                )
                status = ScientistExecutionStatus.FAILED_MODEL
                terminal_reason = "local model call failed"
                break
            raw_digest = self.artifacts.put_bytes(
                model_response.raw_response.encode("utf-8")
            )
            try:
                turn = SCIENTIST_TURN_ADAPTER.validate_json(model_response.raw_response)
            except ValidationError as error:
                records.append(
                    ScientistTurnRecord(
                        turn_number=turn_number,
                        request_artifact_digest=request_digest,
                        response_artifact_digest=raw_digest,
                        raw_response=model_response.raw_response,
                        validation_error=str(error),
                        model_response=model_response,
                    )
                )
                status = ScientistExecutionStatus.FAILED_SCHEMA
                terminal_reason = "model response failed the scientist turn schema"
                break

            if isinstance(turn, FinalScientificResponse):
                final = turn
                reference_errors = self._reference_errors(task, turn)
                records.append(
                    ScientistTurnRecord(
                        turn_number=turn_number,
                        request_artifact_digest=request_digest,
                        response_artifact_digest=raw_digest,
                        raw_response=model_response.raw_response,
                        parsed_kind=turn.kind,
                        model_response=model_response,
                    )
                )
                if reference_errors:
                    status = ScientistExecutionStatus.FAILED_SCHEMA
                    terminal_reason = "final claims referenced undeclared evidence nodes"
                else:
                    status = ScientistExecutionStatus.COMPLETED
                    terminal_reason = None
                break

            tool_request = self._execution_request(task, run_id, turn)
            if (
                tool_request.tool_name in {"graph.query", "evidence.verify", "lineage.backtrack"}
                and (
                    tool_request.arguments.get("graph_digest") != task.graph_artifact_digest
                    or tool_request.arguments.get("source_node_id") not in task.evidence_node_ids
                    or tool_request.arguments.get("target_node_id") not in task.evidence_node_ids
                )
            ):
                result = ExecutionResult(
                    request_id=turn.request_id, run_id=run_id,
                    tool_name=tool_request.tool_name, tool_version=tool_request.tool_version,
                    status=ExecutionStatus.REJECTED, elapsed_seconds=0,
                    error_code="UNDECLARED_GRAPH",
                    error_message="graph or node is outside the frozen task",
                )
            else:
                try:
                    result = self.tools.execute(tool_request)
                except Exception as error:
                    result = ExecutionResult(
                        request_id=turn.request_id, run_id=run_id,
                        tool_name=tool_request.tool_name, tool_version=tool_request.tool_version,
                        status=ExecutionStatus.FAILED, elapsed_seconds=0,
                        error_code=type(error).__name__, error_message="tool executor failed",
                    )
            result_digest = self.artifacts.put_json(result.model_dump(mode="json"))
            records.append(
                ScientistTurnRecord(
                    turn_number=turn_number,
                    request_artifact_digest=request_digest,
                    response_artifact_digest=raw_digest,
                    raw_response=model_response.raw_response,
                    parsed_kind=turn.kind,
                    model_response=model_response,
                    tool_result_artifact_digest=result_digest,
                    tool_succeeded=result.status is ExecutionStatus.SUCCESS,
                )
            )
            if result.status is not ExecutionStatus.SUCCESS:
                status = ScientistExecutionStatus.FAILED_TOOL
                terminal_reason = f"tool request ended with {result.status}"
                break
            messages.append({"role": "assistant", "content": model_response.raw_response})
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        result.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )

        record = ScientistExecutionRecord(
            execution_id=identity,
            run_id=run_id,
            task_artifact_digest=task_digest,
            prompt_artifact_digest=prompt_digest,
            prompt_version=GENOMIC_PROMPT_VERSION,
            policy_version=self.policy.policy_version,
            model_identity=self.adapter.model_identity,
            checkpoint_digest=checkpoint_digest,
            status=status,
            turns=tuple(records),
            final_response=final,
            reference_errors=reference_errors,
            terminal_reason=terminal_reason,
        )
        digest = self.artifacts.put_json(record.model_dump(mode="json"))
        return record.model_copy(update={"artifact_digest": digest})

    def _execution_request(
        self,
        task: GenomicScientistTask,
        run_id: str,
        turn: ToolRequest | GraphQueryRequest | VerificationRequest,
    ) -> ExecutionRequest:
        if isinstance(turn, GraphQueryRequest):
            tool_name = "graph.query"
            tool_version = "1.0.0"
            arguments = {
                "graph_digest": task.graph_artifact_digest,
                "source_node_id": turn.source_node_id,
                "target_node_id": turn.target_node_id,
            }
        elif isinstance(turn, VerificationRequest):
            tool_name = "evidence.verify"
            tool_version = "1.0.0"
            arguments = {
                "graph_digest": task.graph_artifact_digest,
                "source_node_id": turn.claim_node_id,
                "target_node_id": turn.target_node_id,
            }
        else:
            tool_name = turn.tool_name
            tool_version = turn.tool_version
            arguments = turn.arguments
        return ExecutionRequest(
            request_id=turn.request_id,
            run_id=run_id,
            tool_name=tool_name,
            tool_version=tool_version,
            arguments=arguments,
            budget=self.budget,
            policy=self.policy,
        )

    @staticmethod
    def _reference_errors(
        task: GenomicScientistTask, response: FinalScientificResponse
    ) -> tuple[str, ...]:
        allowed = set(task.evidence_node_ids)
        errors: list[str] = []
        for claim in response.claims:
            unknown = sorted(set(claim.evidence_node_ids) - allowed)
            if unknown:
                errors.append(
                    f"claim {claim.claim_id} referenced unknown evidence nodes: {unknown}"
                )
        return tuple(errors)
