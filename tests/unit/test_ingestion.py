from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from pydantic import ValidationError

from concordia.ingestion.parsers import CsvMetadataParser, ParserRegistry, PythonParser
from concordia.ingestion.schema import SourceSpan
from concordia.ingestion.service import ProjectIngestor


def write_fixture_repository(root: Path) -> tuple[Path, ...]:
    files = {
        "README.md": "# Project\n\n## Evidence\nText.\n",
        "module.py": "class Example:\n    def run(self):\n        return 1\n",
        "experiment_manifest.yaml": (
            "experiment_id: exp-1\n"
            "protocol_version: protocol-v1\n"
            "policy_version: policy-v1\n"
            "input_artifact_ids: [abc]\n"
        ),
        "xai_record.json": (
            '{"attribution_id":"a1","model_id":"m1","target":"score",'
            '"attributions":[0.1]}\n'
        ),
        "paper_metadata.json": '{"title":"Example","doi":"10.1/example"}\n',
        "metadata.csv": "dataset_id,assembly\nd1,GRCh38\nd2,GRCh37\n",
        "invalid_xai.json": '{"model_id":"m1"}\n',
        "invalid.py": "def broken(:\n",
    }
    paths = []
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def test_typed_parsers_build_complete_provenance_paths(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = write_fixture_repository(repository)
    ingestor = ProjectIngestor(repository, tmp_path / "state")

    result = ingestor.ingest(paths)

    assert result.file_count == len(paths)
    node_types = {node.node_type for node in result.graph.nodes}
    assert {
        "SourceFile",
        "SourceSpan",
        "ParserRun",
        "DocumentSection",
        "SourceSymbol",
        "ExperimentManifest",
        "Attribution",
        "Paper",
        "Dataset",
        "ExtractionCandidate",
    } <= node_types
    assert result.accepted_entity_count == 9
    assert result.rejected_entity_count == 2

    nodes = {node.node_id: node for node in result.graph.nodes}
    for node in result.graph.nodes:
        if node.node_type in {
            "DocumentSection",
            "SourceSymbol",
            "ExperimentManifest",
            "Attribution",
            "Paper",
            "Dataset",
            "ExtractionCandidate",
        }:
            source = next(
                candidate
                for candidate in result.graph.nodes
                if candidate.node_type == "SourceFile"
                and candidate.properties["relative_path"] == node.properties["relative_path"]
            )
            path = result.graph.path(node.node_id, source.node_id)
            assert path is not None
            assert nodes[path[1]].node_type == "SourceSpan"
    for node in result.graph.nodes:
        if node.node_type == "SourceSpan":
            content = (repository / node.properties["relative_path"]).read_text()
            assert 0 <= node.properties["start_character"] <= len(content)
            assert 0 <= node.properties["end_character"] <= len(content)


def test_unchanged_reingestion_is_idempotent(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    path = repository / "README.md"
    path.write_text("# Stable\n", encoding="utf-8")
    ingestor = ProjectIngestor(repository, tmp_path / "state")

    first = ingestor.ingest((path,))
    second = ingestor.ingest((path,))

    assert second.graph_artifact_digest == first.graph_artifact_digest
    assert second.graph == first.graph
    assert len(ingestor.index.revisions("README.md")) == 1


def test_changed_file_creates_recursive_revision_lineage(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    path = repository / "README.md"
    ingestor = ProjectIngestor(repository, tmp_path / "state")
    path.write_text("# First\n", encoding="utf-8")
    first = ingestor.ingest((path,))
    first_source = next(node for node in first.graph.nodes if node.node_type == "SourceFile")

    path.write_text("# Second\n", encoding="utf-8")
    second = ingestor.ingest((path,))
    second_sources = sorted(
        (node for node in second.graph.nodes if node.node_type == "SourceFile"),
        key=lambda node: node.properties["revision_number"],
    )

    assert len(second_sources) == 2
    assert second_sources[0].node_id == first_source.node_id
    assert second.graph.path(second_sources[1].node_id, second_sources[0].node_id) == (
        second_sources[1].node_id,
        second_sources[0].node_id,
    )
    assert second.graph_artifact_digest != first.graph_artifact_digest


def test_parser_version_change_creates_new_parser_run_not_source_revision(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    path = repository / "README.md"
    path.write_text("# Versioned parser\n", encoding="utf-8")
    state = tmp_path / "state"

    first = ProjectIngestor(
        repository, state, registry=ParserRegistry(version="1.0.0")
    ).ingest((path,))
    second = ProjectIngestor(
        repository, state, registry=ParserRegistry(version="2.0.0")
    ).ingest((path,))

    first_parser = next(node for node in first.graph.nodes if node.node_type == "ParserRun")
    second_parser = next(node for node in second.graph.nodes if node.node_type == "ParserRun")
    assert first_parser.node_id != second_parser.node_id
    assert second_parser.properties["parser_version"] == "2.0.0"
    assert len(ProjectIngestor(repository, state).index.revisions("README.md")) == 1


def test_invalid_spans_and_escaping_paths_are_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError, match="ends before"):
        SourceSpan(
            start_line=2,
            end_line=1,
            start_character=10,
            end_character=1,
        )
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    ingestor = ProjectIngestor(repository, tmp_path / "state")
    with pytest.raises(ValueError, match="escapes repository root"):
        ingestor.ingest((outside,))


def test_discovery_excludes_state_and_unrecognized_files(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Included\n", encoding="utf-8")
    (repository / "notes.txt").write_text("not supported", encoding="utf-8")
    hidden = repository / ".concordia"
    hidden.mkdir()
    (hidden / "ignored.json").write_text("{}", encoding="utf-8")

    discovered = ProjectIngestor(repository, hidden / "ingestion").discover()

    assert [path.name for path in discovered] == ["README.md"]


def test_python_and_multiline_csv_character_spans_are_exact() -> None:
    python_text = "def example():\n    return 'µ'\n"
    python_entity = PythonParser().parse(
        PurePosixPath("module.py"), python_text, "1.0.0"
    ).entities[0]
    assert python_entity.span.end_character == len(python_text.rstrip("\n"))

    csv_text = 'dataset_id,description\nd1,"first\nsecond"\n'
    csv_entity = CsvMetadataParser().parse(
        PurePosixPath("metadata.csv"), csv_text, "1.0.0"
    ).entities[0]
    assert csv_entity.span.start_line == 2
    assert csv_entity.span.end_line == 3
    assert csv_entity.span.end_character == len(csv_text.rstrip("\n"))
