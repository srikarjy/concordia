"""Initial deny-by-default genomic and provenance tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from concordia.cellforge.contracts import (
    FilesystemPolicy,
    NetworkPolicy,
    ResourceBudget,
    ToolCapability,
)
from concordia.cellforge.registry import ExecutionContext, ToolDefinition
from concordia.genomics.evo2 import RecordedFixtureScorer
from concordia.genomics.ism import MutationEffect, scan_position
from concordia.genomics.schema import GenomicSequence, SequenceVariant, apply_variant
from concordia.graph.schema import EvidenceGraph
from concordia.storage.content import ContentAddressedStore
from concordia.verification.backtrack import BacktrackingResult, backtrack_claim


class SequenceValidateInput(GenomicSequence):
    pass


class SequenceValidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: GenomicSequence
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coordinate_convention: str = "zero_based"


class VariantNormalizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: GenomicSequence
    variant: SequenceVariant


class VariantNormalizeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    altered_sequence: GenomicSequence
    coordinate_convention: str = "zero_based"


class ArtifactVerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactVerifyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: str
    byte_size: int = Field(ge=0)
    valid: bool


class GraphQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)


class GraphQueryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: tuple[str, ...] | None


class BacktrackInput(GraphQueryInput):
    pass


class BacktrackOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verification: BacktrackingResult


class MutationalScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: GenomicSequence
    position: int = Field(ge=0)
    scorer_mode: str = Field(default="recorded_fixture", pattern=r"^recorded_fixture$")


class MutationalScanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_mode: str
    effects: tuple[MutationEffect, ...]
    scientific_use_allowed: bool


def validate_sequence(
    arguments: BaseModel, context: ExecutionContext
) -> SequenceValidateOutput:
    del context
    sequence = SequenceValidateInput.model_validate(arguments)
    return SequenceValidateOutput(sequence=sequence, content_hash=sequence.content_hash())


def normalize_variant(
    arguments: BaseModel, context: ExecutionContext
) -> VariantNormalizeOutput:
    del context
    request = VariantNormalizeInput.model_validate(arguments)
    return VariantNormalizeOutput(
        altered_sequence=apply_variant(request.sequence, request.variant)
    )


def verify_artifact(arguments: BaseModel, context: ExecutionContext) -> ArtifactVerifyOutput:
    request = ArtifactVerifyInput.model_validate(arguments)
    payload = ContentAddressedStore(context.artifact_root).get_bytes(request.digest)
    return ArtifactVerifyOutput(digest=request.digest, byte_size=len(payload), valid=True)


def load_graph(digest: str, context: ExecutionContext) -> EvidenceGraph:
    payload = ContentAddressedStore(context.artifact_root).get_bytes(digest)
    return EvidenceGraph.model_validate_json(payload)


def query_graph(arguments: BaseModel, context: ExecutionContext) -> GraphQueryOutput:
    request = GraphQueryInput.model_validate(arguments)
    graph = load_graph(request.graph_digest, context)
    return GraphQueryOutput(path=graph.path(request.source_node_id, request.target_node_id))


def backtrack_lineage(arguments: BaseModel, context: ExecutionContext) -> BacktrackOutput:
    request = BacktrackInput.model_validate(arguments)
    graph = load_graph(request.graph_digest, context)
    return BacktrackOutput(
        verification=backtrack_claim(
            graph, request.source_node_id, request.target_node_id
        )
    )


def verify_evidence(arguments: BaseModel, context: ExecutionContext) -> BacktrackOutput:
    return backtrack_lineage(arguments, context)


def mutational_scan(arguments: BaseModel, context: ExecutionContext) -> MutationalScanOutput:
    del context
    request = MutationalScanInput.model_validate(arguments)
    effects = scan_position(request.sequence, request.position, RecordedFixtureScorer())
    return MutationalScanOutput(
        execution_mode=request.scorer_mode,
        effects=effects,
        scientific_use_allowed=False,
    )


def definition(
    name: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    handler: Any,
    capabilities: frozenset[ToolCapability],
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0.0",
        input_model=input_model,
        output_model=output_model,
        handler=handler,
        required_capabilities=capabilities,
        network=NetworkPolicy.DENY,
        filesystem=FilesystemPolicy.NONE,
        default_budget=ResourceBudget(),
    )


def sequence_validate_definition() -> ToolDefinition:
    return definition(
        "sequence.validate",
        SequenceValidateInput,
        SequenceValidateOutput,
        validate_sequence,
        frozenset({ToolCapability.GENOMIC_COMPUTE}),
    )


def variant_normalize_definition() -> ToolDefinition:
    return definition(
        "variant.normalize",
        VariantNormalizeInput,
        VariantNormalizeOutput,
        normalize_variant,
        frozenset({ToolCapability.GENOMIC_COMPUTE}),
    )


def artifact_verify_definition() -> ToolDefinition:
    return definition(
        "artifact.verify",
        ArtifactVerifyInput,
        ArtifactVerifyOutput,
        verify_artifact,
        frozenset({ToolCapability.ARTIFACT_READ}),
    )


def graph_query_definition() -> ToolDefinition:
    return definition(
        "graph.query",
        GraphQueryInput,
        GraphQueryOutput,
        query_graph,
        frozenset({ToolCapability.ARTIFACT_READ, ToolCapability.GRAPH_READ}),
    )


def lineage_backtrack_definition() -> ToolDefinition:
    return definition(
        "lineage.backtrack",
        BacktrackInput,
        BacktrackOutput,
        backtrack_lineage,
        frozenset({ToolCapability.ARTIFACT_READ, ToolCapability.GRAPH_READ}),
    )


def evidence_verify_definition() -> ToolDefinition:
    return definition(
        "evidence.verify",
        BacktrackInput,
        BacktrackOutput,
        verify_evidence,
        frozenset({ToolCapability.ARTIFACT_READ, ToolCapability.GRAPH_READ}),
    )


def mutational_scan_definition() -> ToolDefinition:
    return definition(
        "xai.mutational_scan",
        MutationalScanInput,
        MutationalScanOutput,
        mutational_scan,
        frozenset({ToolCapability.GENOMIC_COMPUTE}),
    )


BUILTIN_TOOLS = (
    sequence_validate_definition,
    variant_normalize_definition,
    artifact_verify_definition,
    graph_query_definition,
    lineage_backtrack_definition,
    evidence_verify_definition,
    mutational_scan_definition,
)
