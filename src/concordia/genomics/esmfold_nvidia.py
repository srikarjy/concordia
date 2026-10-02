"""NVIDIA-hosted ESMFold protein structure prediction.

Confirmed live against NVIDIA's published OpenAPI schema for this NIM
(``https://build.nvidia.com/nvidia/esmfold``) on 2026-10-02: the endpoint
accepts ``{"sequence": "<amino acids>"}`` and returns ``{"pdbs": [...]}``.
NVIDIA's own product page carries a deprecation notice dated 2026-08-24 —
already past as of this writing — but the endpoint still returns 401 for an
invalid key rather than 410 Gone, meaning it is live for now. It could stop
working without further notice; this module fails closed rather than
assuming availability, and every result is explicitly non-scientific
regardless of structure quality.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from concordia.storage.content import ContentAddressedStore

SHA256_PATTERN = r"^[0-9a-f]{64}$"
AMINO_ACID_PATTERN = r"^[ARNDCQEGHILKMFPSTWYV]+$"


class NvidiaHostedEsmFoldResult(BaseModel):
    """Validated structure-prediction output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["nvidia/esmfold"] = "nvidia/esmfold"
    execution_mode: Literal["real_hosted_structure_prediction"] = (
        "real_hosted_structure_prediction"
    )
    input_sequence_hash: str = Field(pattern=SHA256_PATTERN)
    pdb_text: str = Field(min_length=1)
    elapsed_seconds: float = Field(ge=0)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    response_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class NvidiaHostedEsmFoldRunner:
    """Call NVIDIA's hosted ESMFold NIM and preserve exact request/response bytes."""

    model_id = "nvidia/esmfold"
    endpoint = "https://health.api.nvidia.com/v1/biology/nvidia/esmfold"
    max_sequence_length = 1024
    max_response_bytes = 16 * 1024 * 1024

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.artifacts = artifacts
        self._api_key = os.environ.get("NVIDIA_API_KEY") if api_key is None else api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def predict(self, sequence: str) -> NvidiaHostedEsmFoldResult:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted ESMFold prediction")
        normalized = sequence.strip().upper()
        if not normalized or len(normalized) > self.max_sequence_length:
            raise ValueError(
                f"sequence must be 1-{self.max_sequence_length} amino acids, "
                f"got {len(normalized)}"
            )
        if not re.fullmatch(AMINO_ACID_PATTERN, normalized):
            invalid = sorted(set(normalized) - set("ARNDCQEGHILKMFPSTWYV"))
            raise ValueError(
                f"sequence contains characters outside the 20 standard amino acids: "
                f"{''.join(invalid)}"
            )
        request_payload = {"sequence": normalized}
        input_hash = hashlib.sha256(normalized.encode("ascii")).hexdigest()
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_sequence": normalized,
                "request": request_payload,
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
                json=request_payload,
            )
        elapsed_seconds = time.monotonic() - started
        if len(response.content) > self.max_response_bytes:
            raise RuntimeError("NVIDIA ESMFold response exceeded the configured limit")
        response_digest = self.artifacts.put_bytes(response.content)
        if response.status_code == 410:
            raise RuntimeError(
                "NVIDIA ESMFold has been retired (HTTP 410); this hosted NIM is no "
                "longer available"
            )
        if response.is_error:
            detail = response.text[:1_000].replace("\n", " ")
            raise RuntimeError(f"NVIDIA ESMFold HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("NVIDIA ESMFold response was not JSON") from error
        pdbs = payload.get("pdbs")
        if not isinstance(pdbs, list) or not pdbs or not isinstance(pdbs[0], str):
            raise RuntimeError("NVIDIA ESMFold response contained no PDB structure")
        pdb_text = pdbs[0]
        if "ATOM" not in pdb_text:
            raise RuntimeError("NVIDIA ESMFold response did not look like PDB text")
        return NvidiaHostedEsmFoldResult(
            input_sequence_hash=input_hash,
            pdb_text=pdb_text,
            elapsed_seconds=elapsed_seconds,
            request_artifact_digest=request_digest,
            response_artifact_digest=response_digest,
            limitations=(
                "Hosted structure prediction is a software integration check, not a "
                "validated protein structure.",
                "ESMFold confidence (pLDDT) has not been inspected or thresholded here.",
                "This NIM carries an NVIDIA-published deprecation notice (2026-08-24) "
                "and may stop responding at any time.",
                "The input protein is not biologically verified to be encoded by any "
                "real organism's genome.",
            ),
        )
