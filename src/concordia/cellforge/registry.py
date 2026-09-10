"""Trusted registry of versioned scientific tool handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from concordia.cellforge.contracts import (
    FilesystemPolicy,
    NetworkPolicy,
    ResourceBudget,
    ToolCapability,
)


@dataclass(frozen=True)
class ExecutionContext:
    artifact_root: Path
    workspace_root: Path
    sandbox_root: Path


ToolHandler = Callable[[BaseModel, ExecutionContext], BaseModel]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    required_capabilities: frozenset[ToolCapability]
    network: NetworkPolicy
    filesystem: FilesystemPolicy
    default_budget: ResourceBudget
    path_arguments: tuple[str, ...] = ()

    def manifest(self) -> dict[str, object]:
        """Return the complete, serializable declaration for this tool."""
        return {
            "name": self.name,
            "version": self.version,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
            "required_capabilities": sorted(self.required_capabilities),
            "network_policy": self.network,
            "filesystem_policy": self.filesystem,
            "resource_budget": self.default_budget.model_dump(mode="json"),
            "path_arguments": list(self.path_arguments),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        key = (definition.name, definition.version)
        if key in self._definitions:
            raise ValueError(f"tool is already registered: {definition.name}@{definition.version}")
        self._definitions[key] = definition

    def resolve(self, name: str, version: str) -> ToolDefinition | None:
        return self._definitions.get((name, version))

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


def build_default_registry() -> ToolRegistry:
    from concordia.tools.builtin import BUILTIN_TOOLS

    registry = ToolRegistry()
    for definition in BUILTIN_TOOLS:
        registry.register(definition())
    return registry
