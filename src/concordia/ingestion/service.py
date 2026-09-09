"""Build deterministic evidence graphs from repository files."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from concordia.graph.schema import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphRelation,
)
from concordia.ingestion.index import IngestionIndex, SourceRevision
from concordia.ingestion.parsers import ParserRegistry
from concordia.ingestion.schema import ParsedEntity, ValidationStatus
from concordia.storage.content import ContentAddressedStore

EXCLUDED_PARTS = frozenset(
    {".git", ".venv", ".concordia", "__pycache__", "artifacts", "build", "dist"}
)


class IngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    graph_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_count: int = Field(ge=0)
    accepted_entity_count: int = Field(ge=0)
    rejected_entity_count: int = Field(ge=0)
    graph: EvidenceGraph


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()}"


def edge(source: str, target: str, relation: GraphRelation) -> GraphEdge:
    return GraphEdge(
        edge_id=stable_id("edge", source, target, relation),
        source=source,
        target=target,
        relation=relation,
    )


class ProjectIngestor:
    def __init__(
        self,
        repository_root: str | Path,
        state_root: str | Path,
        *,
        registry: ParserRegistry | None = None,
        max_file_bytes: int = 5_000_000,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.state_root = Path(state_root)
        self.registry = registry or ParserRegistry()
        self.max_file_bytes = max_file_bytes
        self.artifacts = ContentAddressedStore(self.state_root / "artifacts")
        self.index = IngestionIndex(self.state_root / "ingestion.sqlite3")

    def discover(self) -> tuple[Path, ...]:
        paths = []
        for path in self.repository_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.registry.supported_suffixes:
                continue
            relative = path.relative_to(self.repository_root)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if relative.parts[:2] == ("data", "raw"):
                continue
            if path.stat().st_size <= self.max_file_bytes:
                paths.append(path)
        return tuple(sorted(paths, key=lambda value: value.as_posix()))

    def ingest_repository(self) -> IngestionResult:
        return self.ingest(self.discover())

    def ingest(self, paths: tuple[str | Path, ...]) -> IngestionResult:
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        accepted = 0
        rejected = 0
        normalized = sorted(
            (self._resolve_path(path) for path in paths),
            key=lambda pair: pair[0].as_posix(),
        )
        for relative, absolute in normalized:
            payload = absolute.read_bytes()
            if len(payload) > self.max_file_bytes:
                raise ValueError(f"file exceeds ingestion size limit: {relative.as_posix()}")
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"file is not UTF-8 text: {relative.as_posix()}") from error
            digest = self.artifacts.put_bytes(payload)
            source_node_id = stable_id("source", relative.as_posix(), digest)
            revision = self.index.record(relative.as_posix(), digest, source_node_id)
            self._add_revision_lineage(nodes, edges, relative, revision)
            parsed = self.registry.parse(relative, text)
            parser_run_id = stable_id(
                "parser",
                relative.as_posix(),
                digest,
                parsed.parser_name,
                parsed.parser_version,
            )
            nodes[parser_run_id] = GraphNode(
                node_id=parser_run_id,
                node_type=GraphNodeType.PARSER_RUN,
                label=f"{parsed.parser_name} {parsed.parser_version}",
                properties={
                    "parser_name": parsed.parser_name,
                    "parser_version": parsed.parser_version,
                    "file_digest": digest,
                },
            )
            parser_edge = edge(parser_run_id, source_node_id, GraphRelation.USED)
            edges[parser_edge.edge_id] = parser_edge
            for index, entity in enumerate(parsed.entities):
                if entity.validation_status is ValidationStatus.ACCEPTED:
                    accepted += 1
                else:
                    rejected += 1
                self._add_entity(
                    nodes,
                    edges,
                    relative,
                    digest,
                    parser_run_id,
                    parsed.parser_version,
                    entity,
                    index,
                )
        graph = EvidenceGraph(
            nodes=tuple(nodes[key] for key in sorted(nodes)),
            edges=tuple(edges[key] for key in sorted(edges)),
        )
        graph_digest = self.artifacts.put_json(graph.model_dump(mode="json"))
        return IngestionResult(
            graph_artifact_digest=graph_digest,
            file_count=len(normalized),
            accepted_entity_count=accepted,
            rejected_entity_count=rejected,
            graph=graph,
        )

    def _resolve_path(self, path: str | Path) -> tuple[PurePosixPath, Path]:
        candidate = Path(path)
        absolute = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.repository_root / candidate).resolve()
        )
        if not absolute.is_relative_to(self.repository_root):
            raise ValueError("ingestion path escapes repository root")
        if not absolute.is_file():
            raise ValueError(f"ingestion path is not a file: {path}")
        relative = PurePosixPath(absolute.relative_to(self.repository_root).as_posix())
        if relative.suffix.lower() not in self.registry.supported_suffixes:
            raise ValueError(f"unsupported ingestion file type: {relative.suffix}")
        return relative, absolute

    def _add_revision_lineage(
        self,
        nodes: dict[str, GraphNode],
        edges: dict[str, GraphEdge],
        relative: PurePosixPath,
        current: SourceRevision,
    ) -> None:
        revisions = self.index.revisions(relative.as_posix())
        for revision in revisions:
            nodes[revision.node_id] = GraphNode(
                node_id=revision.node_id,
                node_type=GraphNodeType.SOURCE_FILE,
                label=relative.as_posix(),
                properties={
                    "relative_path": relative.as_posix(),
                    "file_digest": revision.digest,
                    "artifact_digest": revision.digest,
                    "revision_number": revision.revision_number,
                },
            )
        for previous, following in zip(revisions, revisions[1:], strict=False):
            revision_edge = edge(
                following.node_id, previous.node_id, GraphRelation.WAS_REVISION_OF
            )
            edges[revision_edge.edge_id] = revision_edge
        if not revisions or revisions[-1] != current:
            raise RuntimeError("source revision index failed to persist current input")

    @staticmethod
    def _add_entity(
        nodes: dict[str, GraphNode],
        edges: dict[str, GraphEdge],
        relative: PurePosixPath,
        digest: str,
        parser_run_id: str,
        parser_version: str,
        entity: ParsedEntity,
        index: int,
    ) -> None:
        identity_parts = (
            relative.as_posix(),
            digest,
            parser_run_id,
            str(index),
            entity.node_type,
            entity.label,
        )
        span_node_id = stable_id("span", *identity_parts)
        entity_node_id = stable_id("entity", *identity_parts)
        common: dict[str, Any] = {
            "relative_path": relative.as_posix(),
            "file_digest": digest,
            "parser_version": parser_version,
            "start_line": entity.span.start_line,
            "end_line": entity.span.end_line,
            "start_character": entity.span.start_character,
            "end_character": entity.span.end_character,
            "extraction_method": entity.extraction_method,
            "extraction_confidence": entity.extraction_confidence,
            "validation_status": entity.validation_status,
            "assertion_status": (
                "validated_extraction"
                if entity.validation_status is ValidationStatus.ACCEPTED
                else "rejected_candidate"
            ),
        }
        nodes[span_node_id] = GraphNode(
            node_id=span_node_id,
            node_type=GraphNodeType.SOURCE_SPAN,
            label=f"{relative.as_posix()}:{entity.span.start_line}",
            properties=common,
        )
        node_type = (
            entity.node_type
            if entity.validation_status is ValidationStatus.ACCEPTED
            else GraphNodeType.EXTRACTION_CANDIDATE
        )
        nodes[entity_node_id] = GraphNode(
            node_id=entity_node_id,
            node_type=node_type,
            label=entity.label,
            properties={
                **common,
                **entity.properties,
                "validation_reasons": entity.validation_reasons,
            },
        )
        generated = edge(span_node_id, parser_run_id, GraphRelation.WAS_GENERATED_BY)
        quoted = edge(entity_node_id, span_node_id, GraphRelation.QUOTED_FROM)
        edges[generated.edge_id] = generated
        edges[quoted.edge_id] = quoted
