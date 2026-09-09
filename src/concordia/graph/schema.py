"""Small validated evidence graph with explicit provenance edges."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GraphNodeType(StrEnum):
    SOURCE_FILE = "SourceFile"
    SOURCE_SPAN = "SourceSpan"
    PARSER_RUN = "ParserRun"
    DATASET = "Dataset"
    SEQUENCE = "Sequence"
    GENOMIC_SEQUENCE = "GenomicSequence"
    VARIANT = "Variant"
    MODEL = "Model"
    CHECKPOINT = "Checkpoint"
    PREDICTION = "Prediction"
    MODEL_OUTPUT = "ModelOutput"
    ATTRIBUTION = "Attribution"
    COUNTERFACTUAL_EFFECT = "CounterfactualEffect"
    PAPER = "Paper"
    CLAIM = "Claim"
    SCIENTIFIC_CLAIM = "ScientificClaim"
    TOOL_RUN = "ToolRun"
    ARTIFACT = "Artifact"
    DOCUMENT_SECTION = "DocumentSection"
    SOURCE_SYMBOL = "SourceSymbol"
    EXPERIMENT_MANIFEST = "ExperimentManifest"
    EXTRACTION_CANDIDATE = "ExtractionCandidate"


class GraphRelation(StrEnum):
    USED = "used"
    WAS_GENERATED_BY = "wasGeneratedBy"
    WAS_DERIVED_FROM = "wasDerivedFrom"
    WAS_REVISION_OF = "wasRevisionOf"
    QUOTED_FROM = "quotedFrom"
    SUPPORTED_BY = "supportedBy"
    CONTRADICTED_BY = "contradictedBy"
    LEGACY_SUPPORTED_BY = "supported_by"
    LEGACY_DERIVED_FROM = "derived_from"


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1)
    node_type: GraphNodeType
    label: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: GraphRelation
    properties: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> EvidenceGraph:
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("graph contains duplicate node IDs")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("graph contains duplicate edge IDs")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
        return self

    def path(self, source: str, target: str) -> tuple[str, ...] | None:
        """Return the shortest directed provenance path between two nodes."""
        adjacency: dict[str, list[str]] = {}
        for edge in self.edges:
            adjacency.setdefault(edge.source, []).append(edge.target)
        queue: deque[tuple[str, tuple[str, ...]]] = deque([(source, (source,))])
        visited = {source}
        while queue:
            current, current_path = queue.popleft()
            if current == target:
                return current_path
            for neighbor in sorted(adjacency.get(current, [])):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, (*current_path, neighbor)))
        return None
