"""Provider-neutral scientist model boundary and local Ollama implementation."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

from concordia.scientist.contracts import ModelResponse


class ScientistModelAdapter(Protocol):
    @property
    def request_settings(self) -> dict[str, Any]: ...

    @property
    def model_identity(self) -> str: ...

    @property
    def checkpoint_digest(self) -> str | None: ...

    def generate(
        self,
        messages: Sequence[dict[str, str]],
        response_schema: dict[str, Any],
    ) -> ModelResponse: ...


class OllamaScientistAdapter:
    """Stateless loopback-only model calls with exact local checkpoint metadata."""

    def __init__(
        self,
        model: str,
        *,
        host: str = "http://127.0.0.1:11434",
        temperature: float = 0.0,
        seed: int | None = None,
        timeout_seconds: float = 300.0,
    ):
        address = urlsplit(host)
        if (
            address.scheme != "http"
            or address.hostname not in {"127.0.0.1", "localhost", "::1"}
            or address.username is not None
            or address.password is not None
            or address.path not in {"", "/"}
            or address.query
            or address.fragment
        ):
            raise ValueError("local scientist backend must use a loopback host")
        self._model = model
        self.host = host
        self.temperature = temperature
        self.seed = seed
        self.timeout_seconds = timeout_seconds
        self._checkpoint_digest: str | None = None
        self._model_details: dict[str, Any] = {}

    @property
    def request_settings(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.temperature, "num_predict": 1024, "num_ctx": 8192,
        }
        if self.seed is not None:
            options["seed"] = self.seed
        return {
            "host": self.host,
            "model": self._model,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": "1s",
            "timeout_seconds": self.timeout_seconds,
            "options": options,
            "transport_version": "ollama-json-v1",
        }

    @property
    def model_identity(self) -> str:
        return self._model

    @property
    def checkpoint_digest(self) -> str | None:
        self._load_identity()
        return self._checkpoint_digest

    def _client(self) -> Any:
        if os.environ.get("OLLAMA_NO_CLOUD") != "1":
            raise RuntimeError("set OLLAMA_NO_CLOUD=1 before local scientist calls")
        try:
            from ollama import Client
        except ImportError as error:
            raise RuntimeError("install the optional scientist dependency first") from error
        return Client(host=self.host, timeout=self.timeout_seconds)

    def _load_identity(self) -> None:
        if self._model_details:
            return
        response = self._client().show(self._model)
        payload = response.model_dump(mode="json")
        self._model_details = {
            key: value for key, value in (payload.get("details") or {}).items()
            if key in {"format", "family", "families", "parameter_size", "quantization_level"}
        }
        modelfile = payload.get("modelfile") or ""
        match = re.search(r"^FROM[^\n]*sha256-([0-9a-f]{64})", modelfile, re.MULTILINE)
        self._checkpoint_digest = match.group(1) if match else None
        if self._checkpoint_digest is None:
            self._model_details = {}
            raise RuntimeError("model must resolve to an installed local checkpoint digest")

    def generate(
        self,
        messages: Sequence[dict[str, str]],
        response_schema: dict[str, Any],
    ) -> ModelResponse:
        if os.environ.get("OLLAMA_NO_CLOUD") != "1":
            raise RuntimeError("set OLLAMA_NO_CLOUD=1 before local scientist calls")
        self._load_identity()
        options = self.request_settings["options"]
        started = time.monotonic()
        response = self._client().chat(
            model=self._model,
            messages=list(messages),
            format="json",
            options=options,
            stream=False,
            think=False,
            keep_alive="1s",
        )
        elapsed = time.monotonic() - started
        payload = response.model_dump(mode="json")
        message = payload.get("message") or {}
        raw = message.get("content")
        if not isinstance(raw, str):
            raise RuntimeError("local model returned no text response")
        memory_bytes: int | None = None
        try:
            processes = self._client().ps().model_dump(mode="json").get("models") or []
            active = next(
                (item for item in processes if item.get("name") == self._model), None
            )
            if active is not None:
                memory_bytes = int(active.get("size") or 0) or None
        except Exception:
            memory_bytes = None
        return ModelResponse(
            raw_response=raw,
            model_identity=str(payload.get("model") or self._model),
            checkpoint_digest=self._checkpoint_digest,
            elapsed_seconds=elapsed,
            input_tokens=payload.get("prompt_eval_count"),
            output_tokens=payload.get("eval_count"),
            memory_bytes=memory_bytes,
            metadata={
                "runtime": "ollama",
                "transport_version": "ollama-json-v1",
                "response_schema": response_schema,
                "host": self.host,
                "temperature": self.temperature,
                "seed": self.seed,
                "model_details": self._model_details,
                "done_reason": payload.get("done_reason"),
                "total_duration_nanoseconds": payload.get("total_duration"),
                "provider_response": payload,
            },
        )
