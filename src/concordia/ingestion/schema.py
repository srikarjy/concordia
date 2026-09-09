"""Contracts shared by deterministic source parsers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from concordia.graph.schema import GraphNodeType


class ValidationStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_character: int = Field(ge=0)
    end_character: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> SourceSpan:
        if self.end_line < self.start_line:
            raise ValueError("source span ends before it starts")
        if self.end_character < self.start_character:
            raise ValueError("source character span ends before it starts")
        return self


class ParsedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: GraphNodeType
    label: str = Field(min_length=1)
    span: SourceSpan
    extraction_method: str = Field(min_length=1)
    extraction_confidence: float = Field(ge=0, le=1)
    validation_status: ValidationStatus
    validation_reasons: tuple[str, ...] = ()
    properties: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    entities: tuple[ParsedEntity, ...]
