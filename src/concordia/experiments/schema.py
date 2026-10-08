"""Typed contracts for the Concordia molecular experimentation DAG."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExperimentNodeKind(StrEnum):
    DNA_SEQUENCE = "dna_sequence"
    PROTEIN_SEQUENCE = "protein_sequence"
    STRUCTURE = "structure"
    MODEL_RUN = "model_run"
    MEASUREMENT = "measurement"
    EVIDENCE = "evidence"


class ExperimentOperation(StrEnum):
    ROOT = "root"
    GENERATE = "generate"
    EDIT = "edit"
    MUTATE = "mutate"
    SCORE = "score"
    ATTRIBUTION = "attribution"
    DESIGN_SEQUENCE = "design_sequence"
    PREDICT_STRUCTURE = "predict_structure"
    DOCK = "dock"
    COMPARE = "compare"
    IMPORT = "import"


class DnaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["dna"] = "dna"
    sequence: str = Field(min_length=1, max_length=1_000_000)
    assembly: str | None = None
    region: str | None = None

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        invalid = sorted(set(normalized) - set("ACGTN"))
        if invalid:
            raise ValueError(f"DNA sequence contains invalid bases: {''.join(invalid)}")
        return normalized


class ProteinPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["protein"] = "protein"
    sequence: str = Field(min_length=1, max_length=100_000)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        invalid = sorted(set(normalized) - set("ARNDCQEGHILKMFPSTWYVX"))
        if invalid:
            raise ValueError(f"protein sequence contains invalid residues: {''.join(invalid)}")
        return normalized


class StructurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["structure"] = "structure"
    format: Literal["pdb", "mmcif"]
    structure_text: str = Field(min_length=1, max_length=32 * 1024 * 1024)


class ModelRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["model_run"] = "model_run"
    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    execution_mode: str = Field(min_length=1)


class MeasurementPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    payload_type: Literal["measurement"] = "measurement"
    metric: str = Field(min_length=1)
    value: float
    unit: str | None = None
    method: str = Field(min_length=1)


class EvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_type: Literal["evidence"] = "evidence"
    evidence_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source: str = Field(min_length=1)


ExperimentPayload = Annotated[
    DnaPayload
    | ProteinPayload
    | StructurePayload
    | ModelRunPayload
    | MeasurementPayload
    | EvidencePayload,
    Field(discriminator="payload_type"),
]


class MutationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=0)
    reference: str = Field(min_length=1, max_length=1)
    alternate: str = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def changes_symbol(self) -> MutationRecord:
        if self.reference.upper() == self.alternate.upper():
            raise ValueError("mutation alternate must differ from reference")
        return self


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experiment_id: str
    title: str
    description: str
    created_at: datetime


class CreateExperimentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment: ExperimentRecord
    access_token: str


class CreateExperimentNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ExperimentNodeKind
    operation: ExperimentOperation
    label: str = Field(min_length=1, max_length=200)
    branch: str = Field(default="main", min_length=1, max_length=100)
    parent_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    payload: ExperimentPayload
    mutations: tuple[MutationRecord, ...] = Field(default_factory=tuple, max_length=10_000)
    evidence_artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    scientific_use_allowed: bool = False

    @model_validator(mode="after")
    def validate_kind_and_operation(self) -> CreateExperimentNodeRequest:
        expected = {
            "dna": ExperimentNodeKind.DNA_SEQUENCE,
            "protein": ExperimentNodeKind.PROTEIN_SEQUENCE,
            "structure": ExperimentNodeKind.STRUCTURE,
            "model_run": ExperimentNodeKind.MODEL_RUN,
            "measurement": ExperimentNodeKind.MEASUREMENT,
            "evidence": ExperimentNodeKind.EVIDENCE,
        }[self.payload.payload_type]
        if self.kind != expected:
            raise ValueError(f"payload type {self.payload.payload_type} requires kind {expected}")
        if self.operation == ExperimentOperation.ROOT and self.parent_ids:
            raise ValueError("root nodes cannot have parents")
        if self.operation != ExperimentOperation.ROOT and not self.parent_ids:
            raise ValueError("non-root nodes require at least one parent")
        if self.mutations and self.operation != ExperimentOperation.MUTATE:
            raise ValueError("mutation records require the mutate operation")
        return self


class ExperimentNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    node_id: str
    experiment_id: str
    kind: ExperimentNodeKind
    operation: ExperimentOperation
    label: str
    branch: str
    parent_ids: tuple[str, ...]
    artifact_digest: str
    mutations: tuple[MutationRecord, ...]
    evidence_artifact_digests: tuple[str, ...]
    scientific_use_allowed: bool
    created_at: datetime


class ExperimentEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_id: str
    child_id: str
    relation: Literal["wasDerivedFrom"] = "wasDerivedFrom"


class ExperimentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experiment: ExperimentRecord
    nodes: tuple[ExperimentNode, ...]
    edges: tuple[ExperimentEdge, ...]
    selected_candidate_ids: tuple[str, ...]
    manifest_digest: str


class ExperimentComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    left_node_id: str
    right_node_id: str
    comparable: bool
    kind: ExperimentNodeKind | None
    length_delta: int | None = None
    differing_positions: tuple[int, ...] = ()
    value_delta: float | None = None
    reasons: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(UTC)


def manifest_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
