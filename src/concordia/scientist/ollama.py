"""Optional local Ollama backend for one scientist call."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from concordia.evidence.schema import EvidencePacket
from concordia.scientist.prompt import PROMPT_VERSION, render_messages
from concordia.scientist.schema import ScientistResponse


@dataclass(frozen=True)
class ScientistGeneration:
    raw_response: str
    parsed: ScientistResponse | None
    metadata: dict[str, Any]
    validation_error: str | None = None


def generate_local(
    packet: EvidencePacket,
    model: str,
    temperature: float = 0.0,
    seed: int | None = None,
    timeout_seconds: float = 300.0,
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
    client = Client(host="http://127.0.0.1:11434", timeout=timeout_seconds)
    response = client.chat(
        model=model,
        messages=render_messages(packet),
        format=ScientistResponse.model_json_schema(),
        options=options,
        stream=False,
    )
    raw = response.message.content
    metadata = {
        "runtime": "ollama",
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
