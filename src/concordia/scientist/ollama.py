"""Optional local Ollama backend for one scientist call."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from concordia.evidence.schema import EvidencePacket
from concordia.scientist.prompt import PROMPT_VERSION, render_messages, render_tool_messages
from concordia.scientist.schema import ScientistResponse
from concordia.scientist.session import ToolSessionResult, run_bounded_session
from concordia.scientist.tools import ToolGateway


@dataclass(frozen=True)
class ScientistGeneration:
    raw_response: str
    parsed: ScientistResponse | None
    metadata: dict[str, Any]
    validation_error: str | None = None


@dataclass(frozen=True)
class ScientistToolGeneration:
    result: ToolSessionResult
    metadata: dict[str, Any]


def generate_local(
    packet: EvidencePacket,
    model: str,
    temperature: float = 0.0,
    seed: int | None = None,
    timeout_seconds: float = 300.0,
    host: str = "http://127.0.0.1:11434",
) -> ScientistGeneration:
    """Call Ollama once; transport failures and schema failures remain explicit."""
    if os.environ.get("OLLAMA_NO_CLOUD") != "1":
        raise RuntimeError("Set OLLAMA_NO_CLOUD=1 before local experiment calls")
    try:
        from ollama import Client
    except ImportError as error:
        raise RuntimeError("Install the optional scientist dependency first") from error

    options: dict[str, Any] = {"temperature": temperature}
    if seed is not None:
        options["seed"] = seed
    started = time.monotonic()
    if not host.startswith("http://127.0.0.1") and not host.startswith("http://localhost"):
        raise ValueError("Local scientist backend must use loopback host")
    client = Client(host=host, timeout=timeout_seconds)
    response = client.chat(
        model=model,
        messages=render_messages(packet),
        # Ollama's grammar support varies by model; validate the full Pydantic
        # contract after generation while requesting provider-compatible JSON.
        format="json",
        options=options,
        stream=False,
    )
    raw = response.message.content or ""
    metadata = {
        "runtime": "ollama",
        "host": host,
        "model_requested": model,
        "prompt_version": PROMPT_VERSION,
        "temperature": temperature,
        "seed": seed,
        "elapsed_seconds": time.monotonic() - started,
        "response_metadata": response.model_dump(exclude={"message"}),
    }
    try:
        parsed = ScientistResponse.model_validate_json(raw)
    except Exception as error:
        return ScientistGeneration(raw, None, metadata, str(error))
    return ScientistGeneration(raw, parsed, metadata)


def generate_local_tool_session(
    packet: EvidencePacket,
    gateway: ToolGateway,
    model: str,
    temperature: float = 0.0,
    seed: int | None = None,
    timeout_seconds: float = 300.0,
) -> ScientistToolGeneration:
    """Run the bounded tool protocol using one local Ollama model."""
    if os.environ.get("OLLAMA_NO_CLOUD") != "1":
        raise RuntimeError("Set OLLAMA_NO_CLOUD=1 before local experiment calls")
    try:
        from ollama import Client
    except ImportError as error:
        raise RuntimeError("Install the optional scientist dependency first") from error
    host = "http://127.0.0.1:11434"
    client = Client(host=host, timeout=timeout_seconds)
    options: dict[str, Any] = {"temperature": temperature}
    if seed is not None:
        options["seed"] = seed
    initial_messages = render_tool_messages(packet, sorted(gateway.policy.allowed_tools))
    started = time.monotonic()

    def model_turn(messages: list[dict[str, str]]) -> str:
        response = client.chat(
            model=model,
            messages=messages,
            format="json",
            options=options,
            stream=False,
        )
        return response.message.content or ""

    result = run_bounded_session(packet, gateway, initial_messages, model_turn)
    metadata = {
        "runtime": "ollama",
        "host": host,
        "model_requested": model,
        "prompt_version": PROMPT_VERSION,
        "temperature": temperature,
        "seed": seed,
        "policy_version": gateway.policy.policy_version,
        "elapsed_seconds": time.monotonic() - started,
    }
    return ScientistToolGeneration(result=result, metadata=metadata)
