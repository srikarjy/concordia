"""Deterministic parsers for repository and scientific metadata files."""

from __future__ import annotations

import ast
import csv
import io
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Protocol

import yaml

from concordia.graph.schema import GraphNodeType
from concordia.ingestion.schema import (
    ParsedDocument,
    ParsedEntity,
    SourceSpan,
    ValidationStatus,
)


class SourceParser(Protocol):
    name: str

    def parse(self, path: PurePosixPath, text: str, version: str) -> ParsedDocument: ...


def full_span(text: str) -> SourceSpan:
    lines = text.splitlines(keepends=True)
    return SourceSpan(
        start_line=1,
        end_line=max(1, len(lines)),
        start_character=0,
        end_character=len(text),
    )


def line_offsets(text: str) -> tuple[int, ...]:
    offsets = [0]
    for match in re.finditer(r"\n", text):
        offsets.append(match.end())
    return tuple(offsets)


def rejected_document(
    parser_name: str, version: str, text: str, method: str, reason: str
) -> ParsedDocument:
    return ParsedDocument(
        parser_name=parser_name,
        parser_version=version,
        entities=(
            ParsedEntity(
                node_type=GraphNodeType.EXTRACTION_CANDIDATE,
                label=f"Rejected {parser_name} document",
                span=full_span(text),
                extraction_method=method,
                extraction_confidence=1,
                validation_status=ValidationStatus.REJECTED,
                validation_reasons=(reason,),
            ),
        ),
    )


class MarkdownParser:
    name = "markdown"

    def parse(self, path: PurePosixPath, text: str, version: str) -> ParsedDocument:
        del path
        offsets = line_offsets(text)
        entities = []
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            match = re.match(r"^(#{1,6})[ \t]+(.+?)[ \t]*(?:\r?\n)?$", line)
            if match is None:
                continue
            start = offsets[line_number - 1]
            entities.append(
                ParsedEntity(
                    node_type=GraphNodeType.DOCUMENT_SECTION,
                    label=match.group(2),
                    span=SourceSpan(
                        start_line=line_number,
                        end_line=line_number,
                        start_character=start,
                        end_character=start + len(line.rstrip("\r\n")),
                    ),
                    extraction_method="markdown.heading",
                    extraction_confidence=1,
                    validation_status=ValidationStatus.ACCEPTED,
                    properties={"heading_level": len(match.group(1))},
                )
            )
        return ParsedDocument(
            parser_name=self.name, parser_version=version, entities=tuple(entities)
        )


class PythonParser:
    name = "python_ast"

    def parse(self, path: PurePosixPath, text: str, version: str) -> ParsedDocument:
        del path
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            return rejected_document(
                self.name,
                version,
                text,
                "python.ast",
                f"syntax error at line {error.lineno or 1}",
            )
        offsets = line_offsets(text)
        lines = text.splitlines(keepends=True)
        entities = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end_line = node.end_lineno or node.lineno
            end_column = node.end_col_offset or node.col_offset
            start_column = len(
                lines[node.lineno - 1].encode("utf-8")[: node.col_offset].decode("utf-8")
            )
            character_end_column = len(
                lines[end_line - 1].encode("utf-8")[:end_column].decode("utf-8")
            )
            entities.append(
                ParsedEntity(
                    node_type=GraphNodeType.SOURCE_SYMBOL,
                    label=node.name,
                    span=SourceSpan(
                        start_line=node.lineno,
                        end_line=end_line,
                        start_character=offsets[node.lineno - 1] + start_column,
                        end_character=offsets[end_line - 1] + character_end_column,
                    ),
                    extraction_method="python.ast.definition",
                    extraction_confidence=1,
                    validation_status=ValidationStatus.ACCEPTED,
                    properties={"symbol_kind": type(node).__name__},
                )
            )
        return ParsedDocument(
            parser_name=self.name, parser_version=version, entities=tuple(entities)
        )


def structured_entities(
    path: PurePosixPath,
    text: str,
    value: Any,
    *,
    method: str,
) -> tuple[ParsedEntity, ...]:
    if not isinstance(value, Mapping):
        return ()
    keys = {str(key) for key in value}
    lowered_path = path.as_posix().lower()
    entities = []
    is_manifest = "manifest" in path.stem.lower() or "experiment" in lowered_path
    if is_manifest:
        input_ids = value.get("input_artifact_ids")
        missing = tuple(
            field
            for field, valid in (
                ("protocol_version", bool(str(value.get("protocol_version", "")))),
                ("policy_version", bool(str(value.get("policy_version", "")))),
                (
                    "input_artifact_ids",
                    isinstance(input_ids, list)
                    and bool(input_ids)
                    and all(isinstance(item, str) and item for item in input_ids),
                ),
            )
            if not valid
        )
        entities.append(
            ParsedEntity(
                node_type=(
                    GraphNodeType.EXPERIMENT_MANIFEST
                    if not missing
                    else GraphNodeType.EXTRACTION_CANDIDATE
                ),
                label=str(value.get("experiment_id", value.get("run_id", path.name))),
                span=full_span(text),
                extraction_method=f"{method}.experiment_manifest",
                extraction_confidence=1,
                validation_status=(
                    ValidationStatus.ACCEPTED if not missing else ValidationStatus.REJECTED
                ),
                validation_reasons=(
                    () if not missing else (f"missing required fields: {', '.join(missing)}",)
                ),
                properties={
                    "declared_fields": sorted(keys),
                    "protocol_version": str(value.get("protocol_version", "")),
                    "policy_version": str(value.get("policy_version", "")),
                    "input_artifact_ids": (
                        [str(item) for item in input_ids]
                        if isinstance(input_ids, list)
                        else []
                    ),
                },
            )
        )
    is_xai = (
        "xai" in lowered_path
        or "explanation" in lowered_path
        or bool(keys & {"attributions", "shap_values"})
    )
    if is_xai:
        attribution_values = value.get("attributions", value.get("shap_values"))
        has_values = isinstance(attribution_values, (list, dict)) and bool(
            attribution_values
        )
        missing = tuple(
            field
            for field, present in (
                ("model_id", bool(str(value.get("model_id", "")))),
                ("target", bool(str(value.get("target", "")))),
                ("attributions_or_shap_values", has_values),
            )
            if not present
        )
        entities.append(
            ParsedEntity(
                node_type=(
                    GraphNodeType.ATTRIBUTION
                    if not missing
                    else GraphNodeType.EXTRACTION_CANDIDATE
                ),
                label=str(value.get("attribution_id", path.name)),
                span=full_span(text),
                extraction_method=f"{method}.xai_record",
                extraction_confidence=1,
                validation_status=(
                    ValidationStatus.ACCEPTED if not missing else ValidationStatus.REJECTED
                ),
                validation_reasons=(
                    () if not missing else (f"missing required fields: {', '.join(missing)}",)
                ),
                properties={
                    "declared_fields": sorted(keys),
                    "model_id": str(value.get("model_id", "")),
                    "target": str(value.get("target", "")),
                },
            )
        )
    is_paper = "paper" in lowered_path or "literature" in lowered_path or "doi" in keys
    if is_paper:
        source_id = value.get("source_id", value.get("doi"))
        has_source = isinstance(source_id, str) and bool(source_id)
        missing = tuple(
            field
            for field, valid in (
                ("title", isinstance(value.get("title"), str) and bool(value["title"])),
                ("source_id_or_doi", has_source),
            )
            if not valid
        )
        entities.append(
            ParsedEntity(
                node_type=(
                    GraphNodeType.PAPER
                    if not missing
                    else GraphNodeType.EXTRACTION_CANDIDATE
                ),
                label=str(value.get("title", path.name)),
                span=full_span(text),
                extraction_method=f"{method}.paper_metadata",
                extraction_confidence=1,
                validation_status=(
                    ValidationStatus.ACCEPTED if not missing else ValidationStatus.REJECTED
                ),
                validation_reasons=(
                    () if not missing else (f"missing required fields: {', '.join(missing)}",)
                ),
                properties={
                    "declared_fields": sorted(keys),
                    "source_id": str(source_id or ""),
                },
            )
        )
    return tuple(entities)


class JsonParser:
    name = "json"

    def parse(self, path: PurePosixPath, text: str, version: str) -> ParsedDocument:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            return rejected_document(
                self.name,
                version,
                text,
                "json.loads",
                f"invalid JSON at line {error.lineno} column {error.colno}",
            )
        return ParsedDocument(
            parser_name=self.name,
            parser_version=version,
            entities=structured_entities(path, text, value, method="json"),
        )


class YamlParser:
    name = "yaml"

    def parse(self, path: PurePosixPath, text: str, version: str) -> ParsedDocument:
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as error:
            mark = getattr(error, "problem_mark", None)
            location = f"line {mark.line + 1}" if mark is not None else "unknown line"
            return rejected_document(
                self.name, version, text, "yaml.safe_load", f"invalid YAML at {location}"
            )
        return ParsedDocument(
            parser_name=self.name,
            parser_version=version,
            entities=structured_entities(path, text, value, method="yaml"),
        )


class CsvMetadataParser:
    name = "csv_metadata"

    def parse(self, path: PurePosixPath, text: str, version: str) -> ParsedDocument:
        del path
        try:
            reader = csv.DictReader(io.StringIO(text), strict=True)
            rows = []
            previous_end_line = 1
            for row in reader:
                rows.append((previous_end_line + 1, reader.line_num, row))
                previous_end_line = reader.line_num
        except csv.Error as error:
            return rejected_document(
                self.name, version, text, "csv.DictReader", f"invalid CSV: {error}"
            )
        lines = text.splitlines(keepends=True)
        offsets = line_offsets(text)
        entities = []
        for row_number, (start_line, end_line, row) in enumerate(rows, start=1):
            malformed = None in row or any(value is None for value in row.values())
            end_text = lines[end_line - 1] if end_line <= len(lines) else ""
            label = next(
                (
                    str(row[key])
                    for key in ("dataset_id", "id", "name")
                    if key in row and row[key]
                ),
                f"row-{row_number}",
            )
            entities.append(
                ParsedEntity(
                    node_type=(
                        GraphNodeType.DATASET
                        if not malformed
                        else GraphNodeType.EXTRACTION_CANDIDATE
                    ),
                    label=label,
                    span=SourceSpan(
                        start_line=start_line,
                        end_line=end_line,
                        start_character=(
                            offsets[start_line - 1]
                            if start_line <= len(offsets)
                            else len(text)
                        ),
                        end_character=(
                            offsets[end_line - 1] + len(end_text.rstrip("\r\n"))
                            if end_line <= len(offsets)
                            else len(text)
                        ),
                    ),
                    extraction_method="csv.DictReader.row",
                    extraction_confidence=1,
                    validation_status=(
                        ValidationStatus.REJECTED
                        if malformed
                        else ValidationStatus.ACCEPTED
                    ),
                    validation_reasons=(
                        ("row width does not match header",) if malformed else ()
                    ),
                    properties={
                        "columns": sorted(str(key) for key in row if key is not None),
                        "metadata": {
                            str(key): value for key, value in row.items() if key is not None
                        },
                    },
                )
            )
        return ParsedDocument(
            parser_name=self.name, parser_version=version, entities=tuple(entities)
        )


class ParserRegistry:
    def __init__(self, version: str = "1.0.0"):
        self.version = version
        self._parsers: dict[str, SourceParser] = {
            ".md": MarkdownParser(),
            ".py": PythonParser(),
            ".json": JsonParser(),
            ".yaml": YamlParser(),
            ".yml": YamlParser(),
            ".csv": CsvMetadataParser(),
        }

    @property
    def supported_suffixes(self) -> frozenset[str]:
        return frozenset(self._parsers)

    def parse(self, path: PurePosixPath, text: str) -> ParsedDocument:
        try:
            parser = self._parsers[path.suffix.lower()]
        except KeyError as error:
            raise ValueError(f"no parser registered for {path.suffix}") from error
        return parser.parse(path, text, self.version)
