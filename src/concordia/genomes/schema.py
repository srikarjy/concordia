"""Versioned digital-genome contracts for bounded scientist workflows."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class EvidenceFamily(StrEnum):
    COUNTERFACTUAL = "counterfactual"
    ATTRIBUTION = "attribution"
    BIOLOGICAL_ANNOTATION = "biological_annotation"
    CROSS_MODEL = "cross_model"
    LITERATURE = "literature"


class MutationOperator(StrEnum):
    ADD_VERIFICATION_STEP = "add_verification_step"
    REMOVE_OPTIONAL_VERIFICATION_STEP = "remove_optional_verification_step"
    REPLACE_COMPATIBLE_STEP = "replace_compatible_step"
    REORDER_INDEPENDENT_STEPS = "reorder_independent_steps"
    CHANGE_WINDOW_SIZE = "change_window_size"
    CHANGE_EVIDENCE_THRESHOLD = "change_evidence_threshold"
    CHANGE_RESOURCE_BUDGET = "change_resource_budget"
    SELECT_UNCERTAINTY_PROMPT = "select_uncertainty_prompt"


class PromptReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    digest: str = Field(pattern=SHA256_PATTERN)


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    evidence_family: EvidenceFamily
    required: bool
    depends_on: tuple[str, ...] = ()
    parameters: tuple[tuple[str, int | float | str | bool], ...] = ()


class AttributionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["mutational_scan"] = "mutational_scan"
    target: str = Field(min_length=1)
    window_size: int = Field(ge=4, le=1_000_000)
    coordinate_convention: Literal["zero_based"] = "zero_based"


class VerificationRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_families: tuple[EvidenceFamily, ...] = Field(min_length=1)
    minimum_independent_families: int = Field(ge=1, le=5)
    evidence_threshold: float = Field(ge=0, le=1)
    require_complete_provenance: bool = True
    block_fixture_support: bool = True

    @model_validator(mode="after")
    def validate_independence(self) -> VerificationRequirement:
        if tuple(sorted(self.required_families)) != self.required_families:
            raise ValueError("required evidence families must be unique and sorted")
        if len(set(self.required_families)) != len(self.required_families):
            raise ValueError("required evidence families must be unique and sorted")
        if self.minimum_independent_families > len(self.required_families):
            raise ValueError("independent-family minimum exceeds required families")
        return self


class ResourceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tool_calls: int = Field(ge=1, le=32)
    max_runtime_seconds: float = Field(gt=0, le=1_800)
    max_tokens: int = Field(ge=128, le=32_768)
    max_compute_units: float = Field(gt=0, le=100)


class AgentGenome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    genome_id: str = Field(pattern=SHA256_PATTERN)
    parent_genome_id: str | None = Field(default=None, pattern=SHA256_PATTERN)
    prompt: PromptReference
    workflow: tuple[WorkflowStep, ...] = Field(min_length=1, max_length=16)
    attribution: AttributionConfig
    verification: VerificationRequirement
    resources: ResourceBudget
    uncertainty_prompt_version: Literal["uncertainty-v1", "uncertainty-v2"]
    policy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_workflow(self) -> AgentGenome:
        identifiers = [step.step_id for step in self.workflow]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("workflow step identifiers must be unique")
        known: set[str] = set()
        for step in self.workflow:
            if any(dependency not in known for dependency in step.depends_on):
                raise ValueError("workflow dependencies must refer to earlier steps")
            known.add(step.step_id)
        if self.genome_id != genome_digest(self.model_dump(exclude={"genome_id"}, mode="json")):
            raise ValueError("genome ID does not match canonical genome content")
        return self


class MutationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    mutation_id: str = Field(pattern=SHA256_PATTERN)
    parent_genome_id: str = Field(pattern=SHA256_PATTERN)
    child_genome_id: str = Field(pattern=SHA256_PATTERN)
    operator: MutationOperator
    seed: int
    old_value: Any
    new_value: Any
    validation_result: Literal["VALID", "INVALID"]
    validation_error: str | None = None


def genome_digest(value: Any) -> str:
    payload = json.dumps(
        to_jsonable_python(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_genome(**values: Any) -> AgentGenome:
    content = to_jsonable_python(values)
    content.setdefault("schema_version", 1)
    content["genome_id"] = genome_digest(content)
    return AgentGenome.model_validate(content)


def create_seed_genome(prompt_digest: str) -> AgentGenome:
    return create_genome(
        parent_genome_id=None,
        prompt=PromptReference(
            prompt_id="genomic-seed-scientist",
            version="genomic-scientist-v3",
            digest=prompt_digest,
        ),
        workflow=(
            WorkflowStep(
                step_id="counterfactual-scan",
                tool_name="xai.mutational_scan",
                tool_version="1.0.0",
                evidence_family=EvidenceFamily.COUNTERFACTUAL,
                required=True,
                parameters=(("window_size", 12),),
            ),
            WorkflowStep(
                step_id="provenance-check",
                tool_name="evidence.verify",
                tool_version="1.0.0",
                evidence_family=EvidenceFamily.ATTRIBUTION,
                required=True,
                depends_on=("counterfactual-scan",),
            ),
            WorkflowStep(
                step_id="optional-graph-query",
                tool_name="graph.query",
                tool_version="1.0.0",
                evidence_family=EvidenceFamily.ATTRIBUTION,
                required=False,
                depends_on=("counterfactual-scan",),
            ),
        ),
        attribution=AttributionConfig(
            target="recorded_fixture.sequence_score", window_size=12
        ),
        verification=VerificationRequirement(
            required_families=(EvidenceFamily.ATTRIBUTION, EvidenceFamily.COUNTERFACTUAL),
            minimum_independent_families=2,
            evidence_threshold=0.75,
        ),
        resources=ResourceBudget(
            max_tool_calls=4,
            max_runtime_seconds=120,
            max_tokens=2_048,
            max_compute_units=4,
        ),
        uncertainty_prompt_version="uncertainty-v1",
        policy_version="seed-scientist-tools-v1",
    )
