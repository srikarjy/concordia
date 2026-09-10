"""Isolated colony-member execution boundary and software-only fixture."""

from __future__ import annotations

import hashlib
from typing import Protocol

from concordia.colonies.schema import MemberExecutionInput, MemberExecutionOutput
from concordia.evaluation import FitnessObservation


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

