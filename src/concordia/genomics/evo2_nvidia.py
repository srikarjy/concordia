"""NVIDIA-hosted Evo2 generation with an explicit forward-inference boundary."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class NvidiaHostedGenerationResult(BaseModel):
    """Validated development output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["arc/evo2-40b-generate"] = "arc/evo2-40b-generate"
    execution_mode: Literal["real_hosted_generation"] = "real_hosted_generation"
    input_sequence_hash: str = Field(pattern=SHA256_PATTERN)
    generated_sequence: str = Field(min_length=1)
    sampled_probabilities: tuple[float, ...]
    elapsed_ms: int | None = Field(default=None, ge=0)
    elapsed_seconds: float = Field(ge=0)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    response_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class NvidiaHostedEvo2GenerationRunner:
    """Call the documented free hosted generation API and preserve exact I/O."""

    model_id = "arc/evo2-40b-generate"
    endpoint = "https://health.api.nvidia.com/v1/biology/arc/evo2-40b/generate"
    max_response_bytes = 16 * 1024 * 1024

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.artifacts = artifacts
        self._api_key = os.environ.get("NVIDIA_API_KEY") if api_key is None else api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def generate(
        self,
        sequence: GenomicSequence,
        *,
        num_tokens: int = 8,
        temperature: float = 0.7,
        top_k: int = 3,
        top_p: float = 0.0,
        random_seed: int = 1729,
    ) -> NvidiaHostedGenerationResult:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted Evo2 generation")
        if not 1 <= num_tokens <= 1_200:
            raise ValueError("num_tokens must be between 1 and 1200")
        if not 0 <= temperature <= 1.3:
            raise ValueError("temperature must be between 0 and 1.3")
        if not 0 <= top_k <= 6:
            raise ValueError("top_k must be between 0 and 6")
        if not 0 <= top_p <= 1:
            raise ValueError("top_p must be between 0 and 1")
        request_payload = {
            "sequence": sequence.sequence,
            "num_tokens": num_tokens,
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "random_seed": random_seed,
            "enable_logits": False,
            "enable_sampled_probs": True,
            "enable_elapsed_ms_per_token": True,
        }
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_sequence": sequence.model_dump(mode="json"),
                "request": request_payload,
                "scientific_use_allowed": False,
            }
        )
        started = time.monotonic()
        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            response = client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=request_payload,
            )
        elapsed_seconds = time.monotonic() - started
        if len(response.content) > self.max_response_bytes:
            raise RuntimeError("NVIDIA Evo2 generation response exceeded the configured limit")
        response_digest = self.artifacts.put_bytes(response.content)
        if response.is_error:
            detail = response.text[:1_000].replace("\n", " ")
            raise RuntimeError(f"NVIDIA Evo2 HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("NVIDIA Evo2 generation response was not JSON") from error
        generated = payload.get("sequence")
        if not isinstance(generated, str):
            raise RuntimeError("NVIDIA Evo2 response contained no generated sequence")
        generated = "".join(generated.upper().split())
        invalid = sorted(set(generated) - set("ACGT"))
        if invalid:
            raise RuntimeError(
                f"NVIDIA Evo2 generated unexpected DNA characters: {''.join(invalid)}"
            )
        if len(generated) != num_tokens:
            raise RuntimeError("NVIDIA Evo2 generated sequence length did not match num_tokens")
        probabilities = payload.get("sampled_probs")
        if (
            not isinstance(probabilities, list)
            or len(probabilities) != num_tokens
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 1
                for value in probabilities
            )
        ):
            raise RuntimeError("NVIDIA Evo2 sampled probabilities were invalid")
        return NvidiaHostedGenerationResult(
            input_sequence_hash=sequence.content_hash(),
            generated_sequence=generated,
            sampled_probabilities=tuple(float(value) for value in probabilities),
            elapsed_ms=payload.get("elapsed_ms"),
            elapsed_seconds=elapsed_seconds,
            request_artifact_digest=request_digest,
            response_artifact_digest=response_digest,
            limitations=(
                "Hosted generation is a software integration check, not an Evo2 forward score.",
                "Generated DNA and sampled probabilities do not establish biological function.",
                "The hosted trial does not expose the forward tensors required by the "
                "frozen study.",
            ),
        )


class NvidiaHostedEvo2Runner:
    """Fail-closed compatibility boundary for the undocumented hosted forward route."""

    checkpoint = "arc/evo2-7b-forward"
    target = "mean_next_base_log_likelihood"

    def __init__(self, artifacts: ContentAddressedStore, **_: object):
        self.artifacts = artifacts

    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, Any]:
        del sequence, checkpoint, target
        raise RuntimeError(
            "NVIDIA's hosted Evo2 trial documents generation only; use a verified local "
            "Evo2 NIM /forward endpoint for scientific scoring"
        )
