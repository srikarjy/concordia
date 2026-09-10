from __future__ import annotations

import hashlib
from pathlib import Path

from concordia.colonies.executor import DeterministicFixtureExecutor
from concordia.colonies.scheduler import ColonyScheduler
from concordia.colonies.schema import (
    ColonySpec,
    ColonyStatus,
    MemberExecutionInput,
    MemberExecutionOutput,
)
from concordia.evaluation import FitnessObservation, evaluate_fitness
from concordia.genomes import create_seed_genome


def make_scheduler(root: Path, factory=None) -> tuple[ColonyScheduler, ColonySpec]:
    scheduler = ColonyScheduler.local(root, factory)
    task_digest = scheduler.artifacts.put_json(
        {
            "schema_version": 1,
            "mode": "software_fixture",
            "scientific_use_allowed": False,
            "question": "frozen genomic attribution audit fixture",
        }
    )
    return scheduler, ColonySpec(
        colony_id="fixture-colony",
        task_artifact_digest=task_digest,
        population_size=3,
        generations=2,
        survivor_count=1,
        max_total_members=6,
    )


def seed():
    return create_seed_genome(hashlib.sha256(b"genomic-scientist-v3").hexdigest())


def test_two_generation_colony_preserves_lineage_and_full_fitness(tmp_path: Path) -> None:
    scheduler, spec = make_scheduler(tmp_path)
    scheduler.create(spec, seed(), idempotency_key="create-1")
    state = scheduler.run(spec.colony_id)

    assert state.status is ColonyStatus.COMPLETED
    assert len(state.members) == 6
    assert len(state.selections) == 2
    assert all(selection.extinct for selection in state.selections)
    assert all(member.parent_member_id for member in state.members)
    first_generation = {member.member_id for member in state.members if member.generation == 1}
    assert all(
        member.parent_member_id in first_generation
        for member in state.members
        if member.generation == 2
    )
    assert all(member.fitness is not None for member in state.members)
    assert all(
        member.fitness.vector.provenance_completeness == 1
        for member in state.members
        if member.fitness is not None
    )
    assert len(state.mutations) >= 6
    assert all(mutation.old_value != mutation.new_value for mutation in state.mutations)


def test_generation_barrier_and_restart_replay(tmp_path: Path) -> None:
    scheduler, spec = make_scheduler(tmp_path)
    scheduler.create(spec, seed(), idempotency_key="restart")
    partial = scheduler.advance(spec.colony_id, max_member_executions=1)
    assert sum(member.output_digest is not None for member in partial.members) == 1

    restarted = ColonyScheduler.local(tmp_path)
    completed = restarted.run(spec.colony_id)
    events = restarted.ledger.events(spec.colony_id)
    selection_one = next(
        event.sequence_number
        for event in events
        if event.event_type == "GENERATION_SELECTED"
        and event.payload["selection"]["generation"] == 1  # type: ignore[index]
    )
    generation_two = min(
        event.sequence_number
        for event in events
        if event.event_type == "MEMBER_SCHEDULED"
        and event.payload["member"]["generation"] == 2  # type: ignore[index]
    )
    assert selection_one < generation_two
    assert restarted.reconstruct(spec.colony_id) == completed


def test_interrupted_running_member_is_recovered_on_resume(tmp_path: Path) -> None:
    scheduler, original = make_scheduler(tmp_path)
    spec = original.model_copy(update={"generations": 1, "max_total_members": 3})
    scheduler.create(spec, seed(), idempotency_key="interrupted")
    scheduler._schedule_generation(scheduler.reconstruct(spec.colony_id), 1)
    scheduled = scheduler.reconstruct(spec.colony_id).members[0]
    scheduler._append(
        spec.colony_id, "MEMBER_STARTED", {"member_id": scheduled.member_id}
    )

    restarted = ColonyScheduler.local(tmp_path)
    state = restarted.run(spec.colony_id)
    assert state.status is ColonyStatus.COMPLETED
    assert all(member.output_digest is not None for member in state.members)
    assert any(
        event.event_type == "MEMBER_RECOVERED"
        for event in restarted.ledger.events(spec.colony_id)
    )


class RecordingFactory:
    def __init__(self) -> None:
        self.requests: list[MemberExecutionInput] = []
        self.executor_ids: list[str] = []

    def create(self, isolation_id: str):
        self.executor_ids.append(isolation_id)
        factory = self

        class Recorder(DeterministicFixtureExecutor):
            def execute(self, request: MemberExecutionInput) -> MemberExecutionOutput:
                factory.requests.append(request)
                return super().execute(request)

        return Recorder(isolation_id)


def test_workers_receive_only_frozen_task_and_own_genome(tmp_path: Path) -> None:
    factory = RecordingFactory()
    scheduler, original = make_scheduler(tmp_path, factory)
    spec = original.model_copy(update={"generations": 1, "max_total_members": 3})
    scheduler.create(spec, seed(), idempotency_key="isolation")
    scheduler.run(spec.colony_id)

    assert len(factory.requests) == 3
    assert len(set(factory.executor_ids)) == 3
    assert "peer" not in MemberExecutionInput.model_fields
    assert "claims" not in MemberExecutionInput.model_fields
    assert all(
        request.task_artifact_digest == spec.task_artifact_digest
        for request in factory.requests
    )


def test_selection_is_reproducible_from_saved_outputs(tmp_path: Path) -> None:
    scheduler, spec = make_scheduler(tmp_path)
    scheduler.create(spec, seed(), idempotency_key="selection")
    state = scheduler.run(spec.colony_id)
    selected = tuple(selection.model_dump(mode="json") for selection in state.selections)

    rebuilt = scheduler.reconstruct(spec.colony_id)
    assert tuple(selection.model_dump(mode="json") for selection in rebuilt.selections) == selected
    for member in rebuilt.members:
        if member.output_digest and member.fitness:
            output = MemberExecutionOutput.model_validate_json(
                scheduler.artifacts.get_bytes(member.output_digest)
            )
            assert evaluate_fitness(output.observation) == member.fitness


def test_cancellation_and_member_budget_are_terminal(tmp_path: Path) -> None:
    cancelled_scheduler, cancelled_spec = make_scheduler(tmp_path / "cancel")
    cancelled_scheduler.create(cancelled_spec, seed(), idempotency_key="cancel")
    cancelled = cancelled_scheduler.cancel(cancelled_spec.colony_id)
    assert cancelled.status is ColonyStatus.CANCELLED
    assert cancelled.members == ()

    budget_scheduler, original = make_scheduler(tmp_path / "budget")
    budget_spec = original.model_copy(update={"max_total_members": 3})
    budget_scheduler.create(budget_spec, seed(), idempotency_key="budget")
    budget = budget_scheduler.run(budget_spec.colony_id)
    assert budget.status is ColonyStatus.BUDGET_EXHAUSTED
    assert len(budget.members) == 3


def test_duplicate_creation_is_idempotent(tmp_path: Path) -> None:
    scheduler, spec = make_scheduler(tmp_path)
    first = scheduler.create(spec, seed(), idempotency_key="same-command")
    second = scheduler.create(spec, seed(), idempotency_key="same-command")
    assert first.event_count == second.event_count == 1


def test_fitness_records_components_and_penalizes_failures() -> None:
    baseline = FitnessObservation(
        provenance_completeness=1,
        evidence_coverage=1,
        counterfactual_consistency=1,
        attribution_direction_agreement=1,
        cross_verification_coverage=1,
        valid_citation_rate=1,
        schema_valid_response_rate=1,
        repeated_run_stability=1,
        tool_success_rate=1,
        runtime_seconds=0,
        token_usage=0,
        compute_usage=0,
        unsupported_claim_penalty=0,
        contradiction_penalty=0,
        tool_failure_penalty=0,
    )
    penalized = baseline.model_copy(
        update={"unsupported_claim_penalty": 1, "contradiction_penalty": 1}
    )
    assert evaluate_fitness(baseline).weighted_score == 1
    assert evaluate_fitness(penalized).weighted_score < 1


class ConstantFactory:
    def create(self, isolation_id: str):
        class ConstantExecutor:
            def execute(self, request: MemberExecutionInput) -> MemberExecutionOutput:
                observation = FitnessObservation(
                    provenance_completeness=1,
                    evidence_coverage=0.5,
                    counterfactual_consistency=0.5,
                    attribution_direction_agreement=0.5,
                    cross_verification_coverage=0.5,
                    valid_citation_rate=0,
                    schema_valid_response_rate=1,
                    repeated_run_stability=1,
                    tool_success_rate=1,
                    runtime_seconds=1,
                    token_usage=128,
                    compute_usage=1,
                    unsupported_claim_penalty=0,
                    contradiction_penalty=0,
                    tool_failure_penalty=0,
                )
                return MemberExecutionOutput(
                    member_id=request.member_id,
                    claim_ids=("fixture-claim",),
                    tool_trace=("fixture",),
                    observation=observation,
                )

        return ConstantExecutor()


def test_stagnation_stops_future_generations(tmp_path: Path) -> None:
    scheduler, original = make_scheduler(tmp_path, ConstantFactory())
    spec = original.model_copy(
        update={
            "generations": 5,
            "max_total_members": 15,
            "stagnation_generations": 2,
        }
    )
    scheduler.create(spec, seed(), idempotency_key="stagnation")
    state = scheduler.run(spec.colony_id)
    assert state.status is ColonyStatus.STAGNATED
    assert len(state.selections) == 2
    assert len(state.members) == 6


class OneFailureFactory:
    def create(self, isolation_id: str):
        if isolation_id.endswith("m0"):
            class FailedExecutor:
                def execute(self, request: MemberExecutionInput) -> MemberExecutionOutput:
                    raise RuntimeError("fixture worker crash")

            return FailedExecutor()
        return DeterministicFixtureExecutor(isolation_id)


def test_worker_failure_is_preserved_and_excluded(tmp_path: Path) -> None:
    scheduler, original = make_scheduler(tmp_path, OneFailureFactory())
    spec = original.model_copy(update={"generations": 1, "max_total_members": 3})
    scheduler.create(spec, seed(), idempotency_key="failure")
    state = scheduler.run(spec.colony_id)
    failed = [member for member in state.members if member.terminal_reason == "RuntimeError"]
    assert len(failed) == 1
    assert any(
        record.member_id == failed[0].member_id and record.reason == "EXECUTION_FAILED"
        for record in state.selections[0].extinct
    )
