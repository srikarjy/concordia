"""Isolated colony-member execution boundary and software-only fixture."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from concordia.cellforge.contracts import (
    NetworkPolicy,
    ResourceBudget,
    SandboxPolicy,
    ToolCapability,
)
from concordia.cellforge.local import LocalExecutionAdapter
from concordia.cellforge.registry import build_default_registry
from concordia.colonies.schema import MemberExecutionInput, MemberExecutionOutput
from concordia.evaluation import FitnessObservation
from concordia.scientist.adapters import OllamaScientistAdapter
from concordia.scientist.contracts import (
    GenomicScientistTask,
    ScientistExecutionStatus,
    ScientistTurnRecord,
)
from concordia.scientist.runtime import SeedScientistRuntime
from concordia.storage.content import ContentAddressedStore


class MemberExecutor(Protocol):
    def execute(self, request: MemberExecutionInput) -> MemberExecutionOutput: ...


class MemberExecutorFactory(Protocol):
    def create(self, isolation_id: str) -> MemberExecutor: ...


class DeterministicFixtureExecutor:
    """Exercises scheduling only; its outputs are barred from scientific use."""

    def __init__(self, isolation_id: str):
        self.isolation_id = isolation_id

    def execute(self, request: MemberExecutionInput) -> MemberExecutionOutput:
        if request.isolation_id != self.isolation_id:
            raise ValueError("executor isolation identity does not match request")
        digest = hashlib.sha256(
            f"{request.task_artifact_digest}:{request.genome.genome_id}".encode()
        ).digest()
        jitter = digest[0] / 2550
        workflow = request.genome.workflow
        tool_count = len(workflow)
        optional_count = sum(not step.required for step in workflow)
        threshold = request.genome.verification.evidence_threshold
        observation = FitnessObservation(
            provenance_completeness=1,
            evidence_coverage=min(1, tool_count / 4),
            counterfactual_consistency=round(0.78 + jitter, 6),
            attribution_direction_agreement=round(0.72 + jitter, 6),
            cross_verification_coverage=min(
                1, len(request.genome.verification.required_families) / 3
            ),
            valid_citation_rate=0,
            schema_valid_response_rate=1,
            repeated_run_stability=1,
            tool_success_rate=1,
            runtime_seconds=round(0.1 * tool_count, 6),
            token_usage=128 + 16 * optional_count,
            compute_usage=round(0.1 * tool_count, 6),
            unsupported_claim_penalty=round(max(0, threshold - 0.75), 6),
            contradiction_penalty=0,
            tool_failure_penalty=0,
        )
        claim_id = hashlib.sha256(
            f"fixture-claim:{request.member_id}:{request.genome.genome_id}".encode()
        ).hexdigest()
        return MemberExecutionOutput(
            member_id=request.member_id,
            claim_ids=(claim_id,),
            tool_trace=tuple(step.tool_name for step in workflow),
            observation=observation,
        )


class DeterministicFixtureExecutorFactory:
    def create(self, isolation_id: str) -> DeterministicFixtureExecutor:
        return DeterministicFixtureExecutor(isolation_id)


class LocalScientistExecutor:
    """Run one isolated local-model session and measure only deterministic behavior."""

    def __init__(
        self,
        isolation_id: str,
        model: str,
        artifacts: ContentAddressedStore,
        workspace_root: Path,
        temporary_root: Path,
        *,
        seed: int,
    ):
        self.isolation_id = isolation_id
        self.model = model
        self.artifacts = artifacts
        self.workspace_root = workspace_root
        self.temporary_root = temporary_root
        self.seed = seed

    def execute(self, request: MemberExecutionInput) -> MemberExecutionOutput:
        if request.isolation_id != self.isolation_id:
            raise ValueError("executor isolation identity does not match request")
        task = GenomicScientistTask.model_validate_json(
            self.artifacts.get_bytes(request.task_artifact_digest)
        )
        workflow = request.genome.workflow
        allowed_tools = frozenset(step.tool_name for step in workflow)
        policy = SandboxPolicy(
            policy_version=request.genome.policy_version,
            allowed_tools=allowed_tools,
            allowed_capabilities=frozenset(
                {
                    ToolCapability.ARTIFACT_READ,
                    ToolCapability.GRAPH_READ,
                    ToolCapability.GENOMIC_COMPUTE,
                }
            ),
            network=NetworkPolicy.DENY,
        )
        genome_context = "; ".join(
            f"{step.step_id}={step.tool_name}@{step.tool_version}"
            for step in workflow
        )
        isolated_task = task.model_copy(
            update={
                "context": (
                    f"{task.context} Your immutable colony workflow is {genome_context}. "
                    f"Use uncertainty policy {request.genome.uncertainty_prompt_version}."
                )
            }
        )
        tool_adapter = LocalExecutionAdapter(
            build_default_registry(),
            workspace_root=self.workspace_root,
            artifact_root=self.artifacts.root,
            temporary_root=self.temporary_root / self.isolation_id,
        )
        runtime = SeedScientistRuntime(
            OllamaScientistAdapter(self.model, temperature=0, seed=self.seed),
            tool_adapter,
            self.artifacts,
            policy,
            max_turns=min(request.genome.resources.max_tool_calls + 1, 20),
            budget=ResourceBudget(
                timeout_seconds=min(request.genome.resources.max_runtime_seconds, 10),
                memory_megabytes=512,
                output_bytes=200_000,
            ),
        )
        record = runtime.run(
            isolated_task,
            run_id=f"colony:{request.member_id}",
            execution_id=f"{self.isolation_id}:{request.member_id}",
        )
        if record.artifact_digest is None:
            raise RuntimeError("scientist execution was not persisted")
        turns = record.turns
        tool_turns = [turn for turn in turns if turn.tool_succeeded is not None]
        successful_tools = sum(turn.tool_succeeded is True for turn in tool_turns)
        tool_success = successful_tools / len(tool_turns) if tool_turns else 1.0
        final = record.final_response
        referenced = (
            {
                evidence_id
                for claim in final.claims
                for evidence_id in claim.evidence_node_ids
            }
            if final is not None
            else set()
        )
        coverage = len(referenced) / len(task.evidence_node_ids)
        completed = record.status is ScientistExecutionStatus.COMPLETED
        runtime_seconds = sum(
            turn.model_response.elapsed_seconds
            for turn in turns
            if turn.model_response is not None
        )
        token_usage = sum(
            (turn.model_response.input_tokens or 0)
            + (turn.model_response.output_tokens or 0)
            for turn in turns
            if turn.model_response is not None
        )
        provenance_complete = self._artifacts_are_valid(record.artifact_digest, turns)
        observation = FitnessObservation(
            provenance_completeness=float(provenance_complete),
            evidence_coverage=min(1.0, coverage),
            counterfactual_consistency=0,
            attribution_direction_agreement=0,
            cross_verification_coverage=0,
            valid_citation_rate=float(
                completed
                and final is not None
                and bool(final.claims)
                and not record.reference_errors
            ),
            schema_valid_response_rate=float(completed),
            repeated_run_stability=0,
            tool_success_rate=tool_success,
            runtime_seconds=runtime_seconds,
            token_usage=token_usage,
            compute_usage=runtime_seconds,
            unsupported_claim_penalty=0,
            contradiction_penalty=0,
            tool_failure_penalty=1 - tool_success,
        )
        return MemberExecutionOutput(
            member_id=request.member_id,
            claim_ids=tuple(claim.claim_id for claim in final.claims) if final else (),
            tool_trace=tuple(
                turn.parsed_kind for turn in turns if turn.parsed_kind is not None
            ),
            observation=observation,
            execution_mode="local_scientist",
            scientist_execution_artifact_digest=record.artifact_digest,
        )

    def _artifacts_are_valid(
        self, record_digest: str, turns: tuple[ScientistTurnRecord, ...]
    ) -> bool:
        digests = [record_digest]
        for turn in turns:
            digests.append(turn.request_artifact_digest)
            if turn.response_artifact_digest:
                digests.append(turn.response_artifact_digest)
            if turn.tool_result_artifact_digest:
                digests.append(turn.tool_result_artifact_digest)
        try:
            return all(bool(self.artifacts.get_bytes(digest)) for digest in digests)
        except (OSError, ValueError):
            return False


class LocalScientistExecutorFactory:
    def __init__(
        self,
        model: str,
        artifacts: ContentAddressedStore,
        workspace_root: str | Path,
        temporary_root: str | Path,
        *,
        seed: int = 1729,
    ):
        self.model = model
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root).resolve()
        self.temporary_root = Path(temporary_root).resolve()
        self.seed = seed

    def create(self, isolation_id: str) -> LocalScientistExecutor:
        return LocalScientistExecutor(
            isolation_id,
            self.model,
            self.artifacts,
            self.workspace_root,
            self.temporary_root,
            seed=self.seed,
        )
