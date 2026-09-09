"""Policy-controlled, deterministic local tools for the single scientist."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from concordia.evidence.schema import EvidencePacket


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    status: Literal["success", "denied", "error"]
    tool: str
    tool_version: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    elapsed_seconds: float = Field(ge=0.0)
    result_hash: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1)
    mode: Literal["evaluation", "researcher"]
    allowed_tools: frozenset[str] = frozenset()
    max_tool_calls: int = Field(default=12, ge=0, le=100)
    max_result_bytes: int = Field(default=200_000, ge=1_000, le=10_000_000)


class ToolGateway:
    """Execute only registered tools allowed by an immutable policy."""

    def __init__(self, policy: ToolPolicy, packet: EvidencePacket):
        self.policy = policy
        self.packet = packet
        self._definitions: dict[str, ToolDefinition] = {}
        self._calls = 0
        self._trace: list[ToolResult] = []

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"Tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def call(self, request: ToolRequest) -> ToolResult:
        started = time.monotonic()
        definition = self._definitions.get(request.tool)
        if self._calls >= self.policy.max_tool_calls:
            return self._record(ToolResult(
                request_id=request.request_id, status="denied", tool=request.tool,
                tool_version=definition.version if definition else "unknown",
                error="tool call limit exceeded", elapsed_seconds=time.monotonic() - started,
            ))
        if request.tool not in self.policy.allowed_tools:
            return self._record(ToolResult(
                request_id=request.request_id, status="denied", tool=request.tool,
                tool_version=definition.version if definition else "unknown",
                error="tool is not allowed by policy", elapsed_seconds=time.monotonic() - started,
            ))
        if definition is None:
            return self._record(ToolResult(
                request_id=request.request_id, status="error", tool=request.tool,
                tool_version="unknown", error="tool is not registered",
                elapsed_seconds=time.monotonic() - started,
            ))
        self._calls += 1
        try:
            result = definition.handler(request.arguments)
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            if len(encoded.encode("utf-8")) > self.policy.max_result_bytes:
                raise ValueError("tool result exceeds policy size limit")
            result_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            return self._record(ToolResult(
                request_id=request.request_id, status="success", tool=request.tool,
                tool_version=definition.version, result=result, result_hash=result_hash,
                elapsed_seconds=time.monotonic() - started,
            ))
        except Exception as error:
            return self._record(ToolResult(
                request_id=request.request_id, status="error", tool=request.tool,
                tool_version=definition.version, error=str(error),
                elapsed_seconds=time.monotonic() - started,
            ))

    def _record(self, result: ToolResult) -> ToolResult:
        self._trace.append(result)
        return result

    @property
    def trace(self) -> tuple[ToolResult, ...]:
        return tuple(self._trace)


def packet_summary(packet: EvidencePacket) -> dict[str, Any]:
    return {
        "packet_id": packet.packet_id,
        "packet_hash": packet.content_hash(),
        "molecule_id": packet.molecule_id,
        "canonical_smiles": packet.canonical_smiles,
        "prediction": packet.prediction.model_dump(mode="json"),
        "has_explanation": packet.explanation is not None,
        "document_ids": [document.evidence_id for document in packet.documents],
    }


def describe_molecule(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic RDKit descriptors for one supplied SMILES."""
    smiles = arguments.get("canonical_smiles")
    if not isinstance(smiles, str) or not smiles:
        raise ValueError("canonical_smiles is required")
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors
    except ImportError as error:
        raise RuntimeError("RDKit is required for molecule description") from error
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError("SMILES is invalid")
    return {
        "canonical_smiles": Chem.MolToSmiles(molecule, canonical=True),
        "heavy_atom_count": int(Descriptors.HeavyAtomCount(molecule)),
        "molecular_weight": float(Descriptors.MolWt(molecule)),
        "logp": float(Descriptors.MolLogP(molecule)),
        "rotatable_bonds": int(Descriptors.NumRotatableBonds(molecule)),
        "ring_count": int(Descriptors.RingCount(molecule)),
    }


def register_read_only_tools(gateway: ToolGateway) -> None:
    gateway.register(
        ToolDefinition(
            "evidence.packet_summary", "evidence-v1", lambda _: packet_summary(gateway.packet)
        )
    )
    gateway.register(
        ToolDefinition("rdkit.describe_molecule", "rdkit-descriptors-v1", describe_molecule)
    )
