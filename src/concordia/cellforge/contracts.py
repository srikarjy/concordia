"""Typed contracts for sandboxed scientific tool execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"


class ToolCapability(StrEnum):
    ARTIFACT_READ = "artifact.read"
    GRAPH_READ = "graph.read"
    GENOMIC_COMPUTE = "genomic.compute"
    FILESYSTEM_READ = "filesystem.read"
    NETWORK = "network"


class NetworkPolicy(StrEnum):
    DENY = "DENY"
    LOOPBACK = "LOOPBACK"
    ALLOW = "ALLOW"


class FilesystemPolicy(StrEnum):
    NONE = "NONE"
    READ_ONLY = "READ_ONLY"


class ResourceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float = Field(default=10, gt=0, le=300)
    memory_megabytes: int = Field(default=512, ge=64, le=16_384)
    output_bytes: int = Field(default=200_000, ge=256, le=10_000_000)


class SandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1)
    allowed_tools: frozenset[str]
    allowed_capabilities: frozenset[ToolCapability]
    network: NetworkPolicy = NetworkPolicy.DENY
    filesystem: FilesystemPolicy = FilesystemPolicy.NONE
    readable_roots: tuple[str, ...] = ()


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    request_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    budget: ResourceBudget = Field(default_factory=ResourceBudget)
    policy: SandboxPolicy


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    request_id: str
    run_id: str
    tool_name: str
    tool_version: str
    status: ExecutionStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    stdout: str = ""
    stderr: str = ""
    elapsed_seconds: float = Field(ge=0)
    scientific_use_allowed: bool = False
