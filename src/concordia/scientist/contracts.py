"""Genomic seed-scientist contracts with no self-assigned verification status."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from concordia.runtime.contracts import Sha256Digest


class ScientistExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED_MODEL = "FAILED_MODEL"
    FAILED_SCHEMA = "FAILED_SCHEMA"
    FAILED_TOOL = "FAILED_TOOL"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class GenomicScientistTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    graph_artifact_digest: Sha256Digest
    claim_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    evidence_node_ids: tuple[str, ...] = Field(min_length=1)
    context: str = Field(min_length=1)
    scientific_use_allowed: bool


class ProposedGenomicClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=2_000)
    evidence_node_ids: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    scope: str = Field(min_length=1, max_length=1_000)
    uncertainty: str = Field(min_length=1, max_length=1_000)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["tool_request"]
    request_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(default="1.0.0", min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class GraphQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["graph_query_request"]
    request_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["verification_request"]
    request_id: str = Field(min_length=1)
    claim_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class FinalScientificResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["final_scientific_response"]
    schema_version: Literal[1] = 1
    summary: str = Field(min_length=1, max_length=3_000)
    claims: tuple[ProposedGenomicClaim, ...]
    limitations: tuple[str, ...] = Field(min_length=1)


ScientistTurn = Annotated[
    ToolRequest | GraphQueryRequest | VerificationRequest | FinalScientificResponse,
    Field(discriminator="kind"),
]
SCIENTIST_TURN_ADAPTER: TypeAdapter[ScientistTurn] = TypeAdapter(ScientistTurn)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_response: str
    model_identity: str = Field(min_length=1)
    checkpoint_digest: str | None = None
    elapsed_seconds: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    memory_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScientistTurnRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_number: int = Field(ge=1)
    request_artifact_digest: Sha256Digest
    response_artifact_digest: Sha256Digest | None = None
    raw_response: str | None = None
    parsed_kind: str | None = None
    validation_error: str | None = None
    model_response: ModelResponse | None = None
    tool_result_artifact_digest: Sha256Digest | None = None
    tool_succeeded: bool | None = None


class ScientistExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    execution_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_artifact_digest: Sha256Digest
    prompt_artifact_digest: Sha256Digest
    prompt_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    model_identity: str = Field(min_length=1)
    checkpoint_digest: str | None = None
    status: ScientistExecutionStatus
    turns: tuple[ScientistTurnRecord, ...]
    final_response: FinalScientificResponse | None = None
    reference_errors: tuple[str, ...] = ()
    terminal_reason: str | None = None
    artifact_digest: Sha256Digest | None = None
