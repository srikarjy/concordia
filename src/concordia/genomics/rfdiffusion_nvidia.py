"""NVIDIA-hosted RFdiffusion binder backbone generation.

RFdiffusion generates a protein *backbone* conditioned on a target structure: no
sequence, only coordinates. It is the first step of a binder design loop, where
ProteinMPNN then assigns a sequence and a structure predictor re-folds the pair.

A designed binder has no experimental structure to compare against, so DockQ and
every other reference metric is undefined for it. That is exactly the regime the
structure verifier is built for (see ``verification/structure_rules.py``): the
only admissible evidence is what can be measured without a crystal.

Requests and responses are kept as artifacts; the target structure is hashed, not
retained. Every result is non-scientific regardless of how good it looks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from concordia.storage.content import ContentAddressedStore

_log = logging.getLogger(__name__)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
# The contig DSL uses chain letters, residue ranges, '/' separators and '0' breaks,
# for example "A20-60/0 50-100". Anything outside that alphabet is rejected.
CONTIG_PATTERN = r"^[A-Za-z0-9/,\- ]+$"
HOTSPOT_PATTERN = r"^[A-Za-z][0-9]{1,5}$"


class RFdiffusionRequest(BaseModel):
    """Validated binder-generation input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_pdb: str | None = Field(default=None, max_length=4_000_000)
    contigs: str = Field(min_length=1, max_length=200)
    hotspot_residues: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    diffusion_steps: int = Field(default=50, ge=1, le=100)
    random_seed: int | None = Field(default=None, ge=0)

    @field_validator("contigs")
    @classmethod
    def validate_contigs(cls, value: str) -> str:
        if not re.fullmatch(CONTIG_PATTERN, value):
            raise ValueError("contigs contains characters outside the RFdiffusion contig DSL")
        return value

    @field_validator("hotspot_residues")
    @classmethod
    def validate_hotspots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        invalid = [item for item in value if not re.fullmatch(HOTSPOT_PATTERN, item)]
        if invalid:
            raise ValueError(f"hotspot residues must look like 'A50', got: {', '.join(invalid)}")
        return value


class NvidiaHostedRFdiffusionResult(BaseModel):
    """Validated backbone output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["ipd/rfdiffusion"] = "ipd/rfdiffusion"
    execution_mode: Literal["real_hosted_backbone_generation"] = "real_hosted_backbone_generation"
    input_payload_hash: str = Field(pattern=SHA256_PATTERN)
    pdb_text: str = Field(min_length=1)
    contigs: str = Field(min_length=1)
    diffusion_steps: int = Field(ge=1)
    random_seed: int | None = None
    elapsed_seconds: float = Field(ge=0)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    response_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class NvidiaHostedRFdiffusionRunner:
    """Call NVIDIA's hosted RFdiffusion NIM and preserve exact request/response bytes."""

    model_id = "ipd/rfdiffusion"
    endpoint = "https://health.api.nvidia.com/v1/biology/ipd/rfdiffusion/generate"
    max_response_bytes = 16 * 1024 * 1024

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 600.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.artifacts = artifacts
        self._api_key = os.environ.get("NVIDIA_API_KEY") if api_key is None else api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def preflight(self) -> None:
        """Reject requests that can never succeed, so a gateway spends no quota on them."""
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted RFdiffusion generation")

    def generate(self, request: RFdiffusionRequest) -> NvidiaHostedRFdiffusionResult:
        self.preflight()
        body: dict[str, object] = {
            "contigs": request.contigs,
            "diffusion_steps": request.diffusion_steps,
        }
        if request.target_pdb is not None:
            body["input_pdb"] = request.target_pdb
        if request.hotspot_residues:
            body["hotspot_res"] = list(request.hotspot_residues)
        if request.random_seed is not None:
            body["random_seed"] = request.random_seed
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        input_hash = hashlib.sha256(canonical).hexdigest()
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_payload_hash": input_hash,
                "target_pdb_bytes": (
                    len(request.target_pdb) if request.target_pdb is not None else None
                ),
                "request_parameters": {
                    "contigs": request.contigs,
                    "hotspot_residues": list(request.hotspot_residues),
                    "diffusion_steps": request.diffusion_steps,
                    "random_seed": request.random_seed,
                },
                "input_retained": False,
                "scientific_use_allowed": False,
            }
        )
        started = time.monotonic()
        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            response = client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                json=body,
            )
        elapsed_seconds = time.monotonic() - started
        if len(response.content) > self.max_response_bytes:
            raise RuntimeError("NVIDIA RFdiffusion response exceeded the configured limit")
        response_digest = self.artifacts.put_bytes(response.content)
        if response.is_error:
            # Upstream detail goes to the server log, not to the (public) caller.
            _log.warning(
                "NVIDIA RFdiffusion HTTP %s: %s",
                response.status_code,
                response.text[:1_000].replace("\n", " "),
            )
            raise RuntimeError(f"NVIDIA RFdiffusion HTTP {response.status_code}")
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("NVIDIA RFdiffusion response was not JSON") from error
        pdb_text = payload.get("output_pdb") if isinstance(payload, dict) else None
        if not isinstance(pdb_text, str) or "ATOM" not in pdb_text:
            raise RuntimeError("NVIDIA RFdiffusion response contained no PDB structure")
        return NvidiaHostedRFdiffusionResult(
            input_payload_hash=input_hash,
            pdb_text=pdb_text,
            contigs=request.contigs,
            diffusion_steps=request.diffusion_steps,
            random_seed=request.random_seed,
            elapsed_seconds=elapsed_seconds,
            request_artifact_digest=request_digest,
            response_artifact_digest=response_digest,
            limitations=(
                "A generated backbone is a design hypothesis, not a binder: nothing here "
                "shows that it folds, expresses, or binds anything.",
                "The backbone carries no sequence. Any sequence must come from a separate "
                "inverse-folding step.",
                "No experimental structure exists for a designed binder, so DockQ and every "
                "other reference metric is undefined; only reference-free checks apply.",
                "RFdiffusion is stochastic. One accepted design out of many attempts is a "
                "selection effect unless the attempt count is reported.",
            ),
        )
