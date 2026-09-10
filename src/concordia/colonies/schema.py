"""Contracts for bounded, isolated colony execution."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from concordia.evaluation import FitnessObservation, FitnessResult
from concordia.genomes import AgentGenome, MutationRecord

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ColonyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    STAGNATED = "STAGNATED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class MemberStatus(StrEnum):
    SEED = "SEED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXTINCT = "EXTINCT"
    CANCELLED = "CANCELLED"


class ColonySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    colony_id: str = Field(min_length=1)
    task_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    population_size: int = Field(default=3, ge=1, le=16)
    generations: int = Field(default=2, ge=1, le=50)
    survivor_count: int = Field(default=1, ge=1, le=16)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    max_total_members: int = Field(default=6, ge=1, le=800)
    stagnation_generations: int = Field(default=3, ge=1, le=50)
    random_seed: int = 1729

    @model_validator(mode="after")
    def validate_bounds(self) -> ColonySpec:
        if self.survivor_count > self.population_size:
            raise ValueError("survivor count cannot exceed population size")
        return self


class MemberExecutionInput(BaseModel):
    """The complete worker view; deliberately contains no peer state or claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    member_id: str
    generation: int = Field(ge=1)
    isolation_id: str
    task_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    genome: AgentGenome


class MemberExecutionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    member_id: str
    claim_ids: tuple[str, ...]
    tool_trace: tuple[str, ...]
    observation: FitnessObservation
    scientific_use_allowed: Literal[False] = False
    execution_mode: Literal["deterministic_colony_fixture"] = (
        "deterministic_colony_fixture"
    )


class ColonyMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    member_id: str
    generation: int = Field(ge=0)
    parent_member_id: str | None
    genome_digest: str = Field(pattern=SHA256_PATTERN)
    mutation_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    isolation_id: str
    status: MemberStatus
    output_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    fitness: FitnessResult | None = None
    terminal_reason: str | None = None


class ExtinctionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    member_id: str
    reason: Literal["LOWER_WEIGHTED_FITNESS", "EXECUTION_FAILED"]


class GenerationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    generation: int = Field(ge=1)
    survivor_ids: tuple[str, ...]
    extinct: tuple[ExtinctionRecord, ...]
    ranked_member_ids: tuple[str, ...]
    rationale: str


class ColonyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    event_id: str
    colony_id: str
    sequence_number: int = Field(ge=1)
    event_type: str
    created_at: datetime
    payload: dict[str, object]


class ColonyState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    spec: ColonySpec
    status: ColonyStatus
    seed_member: ColonyMember
    members: tuple[ColonyMember, ...]
    genomes: tuple[AgentGenome, ...]
    mutations: tuple[MutationRecord, ...]
    selections: tuple[GenerationSelection, ...]
    event_count: int = Field(ge=1)
    terminal_reason: str | None = None

