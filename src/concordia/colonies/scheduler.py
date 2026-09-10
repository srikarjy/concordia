"""Deterministic bounded-colony scheduler reconstructed entirely from events."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from concordia.colonies.executor import (
    DeterministicFixtureExecutorFactory,
    MemberExecutorFactory,
)
from concordia.colonies.schema import (
    ColonyMember,
    ColonySpec,
    ColonyState,
    ColonyStatus,
    ExtinctionRecord,
    GenerationSelection,
    MemberExecutionInput,
    MemberExecutionOutput,
    MemberStatus,
)
from concordia.colonies.store import SQLiteColonyLedger, canonical_json
from concordia.evaluation import FitnessResult, evaluate_fitness
from concordia.genomes import AgentGenome, MutationEngine, MutationOperator, MutationRecord
from concordia.storage.content import ContentAddressedStore

TERMINAL = {
    ColonyStatus.COMPLETED,
    ColonyStatus.CANCELLED,
    ColonyStatus.STAGNATED,
    ColonyStatus.BUDGET_EXHAUSTED,
}


class ColonyScheduler:
    def __init__(
        self,
        ledger: SQLiteColonyLedger,
        artifacts: ContentAddressedStore,
        executor_factory: MemberExecutorFactory | None = None,
    ):
        self.ledger = ledger
        self.artifacts = artifacts
        self.executor_factory = executor_factory or DeterministicFixtureExecutorFactory()
        self.mutations = MutationEngine()

    @classmethod
    def local(
        cls, root: str | Path, executor_factory: MemberExecutorFactory | None = None
    ) -> ColonyScheduler:
        root = Path(root)
        return cls(
            SQLiteColonyLedger(root / "colony.sqlite3"),
            ContentAddressedStore(root / "artifacts"),
            executor_factory,
        )

    def create(
        self, spec: ColonySpec, seed_genome: AgentGenome, *, idempotency_key: str
    ) -> ColonyState:
        genome_digest = self.artifacts.put_json(seed_genome.model_dump(mode="json"))
        seed_member = ColonyMember(
            member_id=f"seed-{seed_genome.genome_id[:16]}",
            generation=0,
            parent_member_id=None,
            genome_digest=genome_digest,
            isolation_id=f"isolation-{spec.colony_id}-seed",
            status=MemberStatus.SEED,
        )
        payload = {
            "spec": spec.model_dump(mode="json"),
            "seed_genome": seed_genome.model_dump(mode="json"),
            "seed_member": seed_member.model_dump(mode="json"),
        }
        request_digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        colony_id = self.ledger.create(
            spec.colony_id, idempotency_key, request_digest, payload
        )
        return self.reconstruct(colony_id)

    def cancel(self, colony_id: str) -> ColonyState:
        state = self.reconstruct(colony_id)
        if state.status in TERMINAL:
            return state
        self._append(colony_id, "CANCELLATION_REQUESTED", {})
        return self.advance(colony_id)

    def run(self, colony_id: str) -> ColonyState:
        state = self.reconstruct(colony_id)
        while state.status not in TERMINAL:
            state = self.advance(colony_id)
        return state

    def advance(
        self, colony_id: str, *, max_member_executions: int | None = None
    ) -> ColonyState:
        state = self.reconstruct(colony_id)
        if state.status in TERMINAL:
            return state
        events = self.ledger.events(colony_id)
        if any(event.event_type == "CANCELLATION_REQUESTED" for event in events):
            for member in state.members:
                if member.status is MemberStatus.SCHEDULED:
                    self._append(
                        colony_id,
                        "MEMBER_CANCELLED",
                        {"member_id": member.member_id},
                    )
            self._append(
                colony_id,
                "COLONY_TERMINATED",
                {"status": ColonyStatus.CANCELLED, "reason": "cancellation requested"},
            )
            return self.reconstruct(colony_id)

        current_generation = len(state.selections) + 1
        current = [member for member in state.members if member.generation == current_generation]
        if not current:
            if len(state.members) + state.spec.population_size > state.spec.max_total_members:
                self._terminate_budget(colony_id)
                return self.reconstruct(colony_id)
            self._schedule_generation(state, current_generation)
            state = self.reconstruct(colony_id)
            current = [m for m in state.members if m.generation == current_generation]

        stale_running = [member for member in current if member.status is MemberStatus.RUNNING]
        for member in stale_running:
            self._append(
                colony_id,
                "MEMBER_RECOVERED",
                {"member_id": member.member_id, "reason": "interrupted execution"},
            )
        if stale_running:
            state = self.reconstruct(colony_id)
            current = [m for m in state.members if m.generation == current_generation]

        pending = [member for member in current if member.status is MemberStatus.SCHEDULED]
        if max_member_executions is not None:
            pending = pending[:max_member_executions]
        if pending:
            self._execute_members(state, pending)
            state = self.reconstruct(colony_id)
            current = [m for m in state.members if m.generation == current_generation]
        if any(member.status is MemberStatus.SCHEDULED for member in current):
            return state

        if not any(selection.generation == current_generation for selection in state.selections):
            self._select_generation(colony_id, current_generation, current, state.spec)
            state = self.reconstruct(colony_id)

        if current_generation >= state.spec.generations:
            self._append(
                colony_id,
                "COLONY_TERMINATED",
                {"status": ColonyStatus.COMPLETED, "reason": "generation limit reached"},
            )
            return self.reconstruct(colony_id)
        if self._is_stagnated(state):
            self._append(
                colony_id,
                "COLONY_TERMINATED",
                {"status": ColonyStatus.STAGNATED, "reason": "fitness stagnation"},
            )
        return self.reconstruct(colony_id)

    def reconstruct(self, colony_id: str) -> ColonyState:
        events = self.ledger.events(colony_id)
        created = events[0].payload
        spec = ColonySpec.model_validate(created["spec"])
        seed_genome = AgentGenome.model_validate(created["seed_genome"])
        seed_member = ColonyMember.model_validate(created["seed_member"])
        genomes: dict[str, AgentGenome] = {seed_genome.genome_id: seed_genome}
        mutations: list[MutationRecord] = []
        members: dict[str, ColonyMember] = {}
        selections: list[GenerationSelection] = []
        status = ColonyStatus.ACTIVE
        terminal_reason = None
        for event in events[1:]:
            payload = event.payload
            if event.event_type == "MUTATION_RECORDED":
                mutation = MutationRecord.model_validate(payload["mutation"])
                mutations.append(mutation)
                if payload.get("genome") is not None:
                    genome = AgentGenome.model_validate(payload["genome"])
                    genomes[genome.genome_id] = genome
            elif event.event_type == "MEMBER_SCHEDULED":
                member = ColonyMember.model_validate(payload["member"])
                members[member.member_id] = member
            elif event.event_type == "MEMBER_STARTED":
                member_id = str(payload["member_id"])
                members[member_id] = members[member_id].model_copy(
                    update={"status": MemberStatus.RUNNING}
                )
            elif event.event_type == "MEMBER_RECOVERED":
                member_id = str(payload["member_id"])
                members[member_id] = members[member_id].model_copy(
                    update={"status": MemberStatus.SCHEDULED}
                )
            elif event.event_type == "MEMBER_COMPLETED":
                member_id = str(payload["member_id"])
                members[member_id] = members[member_id].model_copy(
                    update={
                        "status": MemberStatus.COMPLETED,
                        "output_digest": payload["output_digest"],
                        "fitness": FitnessResult.model_validate(payload["fitness"]),
                    }
                )
            elif event.event_type == "MEMBER_FAILED":
                member_id = str(payload["member_id"])
                members[member_id] = members[member_id].model_copy(
                    update={
                        "status": MemberStatus.FAILED,
                        "terminal_reason": payload["reason"],
                    }
                )
            elif event.event_type == "MEMBER_CANCELLED":
                member_id = str(payload["member_id"])
                members[member_id] = members[member_id].model_copy(
                    update={"status": MemberStatus.CANCELLED}
                )
            elif event.event_type == "GENERATION_SELECTED":
                selection = GenerationSelection.model_validate(payload["selection"])
                selections.append(selection)
                for extinct in selection.extinct:
                    member = members[extinct.member_id]
                    if member.status is MemberStatus.COMPLETED:
                        members[extinct.member_id] = member.model_copy(
                            update={
                                "status": MemberStatus.EXTINCT,
                                "terminal_reason": extinct.reason,
                            }
                        )
            elif event.event_type == "COLONY_TERMINATED":
                status = ColonyStatus(str(payload["status"]))
                terminal_reason = str(payload["reason"])
        return ColonyState(
            spec=spec,
            status=status,
            seed_member=seed_member,
            members=tuple(sorted(members.values(), key=lambda m: (m.generation, m.member_id))),
            genomes=tuple(sorted(genomes.values(), key=lambda genome: genome.genome_id)),
            mutations=tuple(mutations),
            selections=tuple(selections),
            event_count=len(events),
            terminal_reason=terminal_reason,
        )

    def _schedule_generation(self, state: ColonyState, generation: int) -> None:
        parents: tuple[ColonyMember, ...]
        if generation == 1:
            parents = (state.seed_member,)
        else:
            survivor_ids = state.selections[-1].survivor_ids
            by_id = {member.member_id: member for member in state.members}
            parents = tuple(by_id[member_id] for member_id in survivor_ids)
        genomes_by_artifact = {
            self.artifacts.put_json(genome.model_dump(mode="json")): genome
            for genome in state.genomes
        }
        operators = tuple(MutationOperator)
        for index in range(state.spec.population_size):
            parent_member = parents[index % len(parents)]
            parent = genomes_by_artifact[parent_member.genome_digest]
            child = None
            mutation = None
            for offset in range(len(operators)):
                operator_index = (
                    generation * state.spec.population_size + index + offset
                ) % len(operators)
                operator = operators[operator_index]
                mutation_seed = (
                    state.spec.random_seed + generation * 10_000 + index * 100 + offset
                )
                child, mutation = self.mutations.mutate(parent, operator, mutation_seed)
                mutation_payload = {
                    "mutation": mutation.model_dump(mode="json"),
                    "genome": child.model_dump(mode="json") if child else None,
                }
                self._append(state.spec.colony_id, "MUTATION_RECORDED", mutation_payload)
                if child is not None:
                    break
            if child is None or mutation is None:
                raise RuntimeError("no valid mutation operator for parent genome")
            genome_artifact = self.artifacts.put_json(child.model_dump(mode="json"))
            mutation_artifact = self.artifacts.put_json(mutation.model_dump(mode="json"))
            member_id = hashlib.sha256(
                f"{state.spec.colony_id}:{generation}:{index}:{child.genome_id}".encode()
            ).hexdigest()[:24]
            member = ColonyMember(
                member_id=member_id,
                generation=generation,
                parent_member_id=parent_member.member_id,
                genome_digest=genome_artifact,
                mutation_digest=mutation_artifact,
                isolation_id=f"{state.spec.colony_id}-g{generation}-m{index}",
                status=MemberStatus.SCHEDULED,
            )
            self._append(
                state.spec.colony_id,
                "MEMBER_SCHEDULED",
                {"member": member.model_dump(mode="json")},
            )

    def _execute_members(self, state: ColonyState, members: list[ColonyMember]) -> None:
        genome_by_artifact = {
            self.artifacts.put_json(genome.model_dump(mode="json")): genome
            for genome in state.genomes
        }
        requests = [
            MemberExecutionInput(
                member_id=member.member_id,
                generation=member.generation,
                isolation_id=member.isolation_id,
                task_artifact_digest=state.spec.task_artifact_digest,
                genome=genome_by_artifact[member.genome_digest],
            )
            for member in members
        ]
        for request in requests:
            self._append(state.spec.colony_id, "MEMBER_STARTED", {"member_id": request.member_id})

        def execute(
            request: MemberExecutionInput,
        ) -> tuple[MemberExecutionInput, MemberExecutionOutput | Exception]:
            try:
                return request, self.executor_factory.create(request.isolation_id).execute(request)
            except Exception as error:  # execution failures are preserved as terminal members
                return request, error

        if state.spec.max_concurrency == 1:
            results = [execute(request) for request in requests]
        else:
            with ThreadPoolExecutor(max_workers=state.spec.max_concurrency) as pool:
                results = list(pool.map(execute, requests))
        for request, result in sorted(results, key=lambda pair: pair[0].member_id):
            if isinstance(result, Exception):
                self._append(
                    state.spec.colony_id,
                    "MEMBER_FAILED",
                    {"member_id": request.member_id, "reason": type(result).__name__},
                )
                continue
            output_digest = self.artifacts.put_json(result.model_dump(mode="json"))
            fitness = evaluate_fitness(result.observation)
            self._append(
                state.spec.colony_id,
                "MEMBER_COMPLETED",
                {
                    "member_id": request.member_id,
                    "output_digest": output_digest,
                    "fitness": fitness.model_dump(mode="json"),
                },
            )

    def _select_generation(
        self,
        colony_id: str,
        generation: int,
        members: list[ColonyMember],
        spec: ColonySpec,
    ) -> None:
        completed = [member for member in members if member.status is MemberStatus.COMPLETED]
        ranked = sorted(
            completed,
            key=lambda member: (-member.fitness.weighted_score, member.member_id),  # type: ignore[union-attr]
        )
        survivors = tuple(member.member_id for member in ranked[: spec.survivor_count])
        survivor_set = set(survivors)
        extinct = tuple(
            ExtinctionRecord(
                member_id=member.member_id,
                reason=(
                    "EXECUTION_FAILED"
                    if member.status is MemberStatus.FAILED
                    else "LOWER_WEIGHTED_FITNESS"
                ),
            )
            for member in members
            if member.member_id not in survivor_set
        )
        selection = GenerationSelection(
            generation=generation,
            survivor_ids=survivors,
            extinct=extinct,
            ranked_member_ids=tuple(member.member_id for member in ranked),
            rationale=(
                "descending weighted-fitness-v1 score; immutable member identifier breaks ties"
            ),
        )
        self._append(
            colony_id,
            "GENERATION_SELECTED",
            {"selection": selection.model_dump(mode="json")},
        )

    def _is_stagnated(self, state: ColonyState) -> bool:
        count = state.spec.stagnation_generations
        if len(state.selections) < count:
            return False
        by_id = {member.member_id: member for member in state.members}
        scores: list[float] = []
        for selection in state.selections[-count:]:
            if not selection.survivor_ids:
                continue
            fitness = by_id[selection.survivor_ids[0]].fitness
            if fitness is not None:
                scores.append(fitness.weighted_score)
        return len(scores) == count and max(scores) - min(scores) <= 1e-12

    def _terminate_budget(self, colony_id: str) -> None:
        self._append(
            colony_id,
            "COLONY_TERMINATED",
            {"status": ColonyStatus.BUDGET_EXHAUSTED, "reason": "member budget exhausted"},
        )

    def _append(self, colony_id: str, event_type: str, payload: dict[str, Any]) -> None:
        sequence = len(self.ledger.events(colony_id))
        self.ledger.append(
            colony_id, event_type, json.loads(canonical_json(payload)), expected_sequence=sequence
        )
