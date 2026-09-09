"""Bounded, policy-controlled interaction between one scientist and local tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from concordia.evidence.schema import EvidencePacket
from concordia.scientist.schema import ScientistResponse
from concordia.scientist.tools import ToolGateway, ToolRequest, ToolResult


class ScientistTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["tool_request", "final"]
    tool_request: ToolRequest | None = None
    response: ScientistResponse | None = None


class ToolSessionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "failed", "limit_exceeded"]
    response: ScientistResponse | None = None
    error: str | None = None
    tool_trace: tuple[ToolResult, ...] = ()


ModelTurn = Callable[[list[dict[str, str]]], str]


def run_bounded_session(
    packet: EvidencePacket,
    gateway: ToolGateway,
    initial_messages: list[dict[str, str]],
    model_turn: ModelTurn,
) -> ToolSessionResult:
    """Run a finite tool protocol; the model cannot alter policy or tool registry."""
    messages = list(initial_messages)
    for _ in range(gateway.policy.max_tool_calls + 1):
        raw = model_turn(messages)
        try:
            turn = ScientistTurn.model_validate_json(raw)
        except ValidationError as error:
            return ToolSessionResult(
                status="failed", error=f"invalid scientist turn: {error}", tool_trace=gateway.trace
            )
        if turn.kind == "final":
            if turn.response is None or turn.tool_request is not None:
                return ToolSessionResult(
                    status="failed",
                    error="final turn must contain only response",
                    tool_trace=gateway.trace,
                )
            return ToolSessionResult(
                status="completed", response=turn.response, tool_trace=gateway.trace
            )
        if turn.tool_request is None or turn.response is not None:
            return ToolSessionResult(
                status="failed",
                error="tool turn must contain only request",
                tool_trace=gateway.trace,
            )
        result = gateway.call(turn.tool_request)
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "tool",
                "content": json.dumps(
                    result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                ),
            }
        )
    return ToolSessionResult(
        status="limit_exceeded", error="bounded tool session exhausted", tool_trace=gateway.trace
    )
