"""NVIDIA-hosted OpenFold2 protein structure prediction.

OpenFold2 is NVIDIA's PyTorch reimplementation of AlphaFold2 (monomer). It is the
hosted replacement for the retired ESMFold and AlphaFold2 endpoints. Requests keep
the exact request and response bytes as artifacts and never retain the sequence.
Every result is explicitly non-scientific regardless of structure quality.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from concordia.storage.content import ContentAddressedStore

SHA256_PATTERN = r"^[0-9a-f]{64}$"
AMINO_ACID_PATTERN = r"^[ARNDCQEGHILKMFPSTWYV]+$"


class NvidiaHostedOpenFold2Result(BaseModel):
    """Validated structure-prediction output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["openfold/openfold2"] = "openfold/openfold2"
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


def _extract_pdb(payload: Any) -> str | None:
    """Pull the top-ranked PDB text out of the documented response shapes."""
    if not isinstance(payload, dict):
        return None
    ranked = payload.get("structures_in_ranked_order")
    if isinstance(ranked, list) and ranked:
        first = ranked[0]
        if isinstance(first, dict) and isinstance(first.get("structure"), str):
            return str(first["structure"])
        if isinstance(first, str):
            return first
    pdbs = payload.get("pdbs")
    if isinstance(pdbs, list) and pdbs and isinstance(pdbs[0], str):
        return pdbs[0]
    return None


class NvidiaHostedOpenFold2Runner:
    """Call NVIDIA's hosted OpenFold2 NIM and preserve exact request/response bytes."""

    model_id = "openfold/openfold2"
    endpoint = (
        "https://health.api.nvidia.com/v1/biology/openfold/openfold2/"
        "predict-structure-from-msa-and-template"
    )
    max_sequence_length = 1000
    max_response_bytes = 16 * 1024 * 1024

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.artifacts = artifacts
        self._api_key = os.environ.get("NVIDIA_API_KEY") if api_key is None else api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def predict(self, sequence: str) -> NvidiaHostedOpenFold2Result:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted OpenFold2 prediction")
        normalized = sequence.strip().upper()
        if not normalized or len(normalized) > self.max_sequence_length:
            raise ValueError(
                f"sequence must be 1-{self.max_sequence_length} amino acids, "
                f"got {len(normalized)}"
            )
        if not re.fullmatch(AMINO_ACID_PATTERN, normalized):
            invalid = sorted(set(normalized) - set("ARNDCQEGHILKMFPSTWYV"))
            raise ValueError(
                "sequence contains characters outside the 20 standard amino acids: "
                f"{''.join(invalid)}"
            )
        request_payload = {"sequence": normalized}
        input_hash = hashlib.sha256(normalized.encode("ascii")).hexdigest()
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_sequence_hash": input_hash,
                "input_sequence_length": len(normalized),
                "request_parameters": {"msa": "none", "templates": "none"},
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
                json=request_payload,
            )
        elapsed_seconds = time.monotonic() - started
        if len(response.content) > self.max_response_bytes:
            raise RuntimeError("NVIDIA OpenFold2 response exceeded the configured limit")
        response_digest = self.artifacts.put_bytes(response.content)
        if response.status_code == 410:
            raise RuntimeError("NVIDIA OpenFold2 has been retired (HTTP 410)")
        if response.is_error:
            detail = response.text[:1_000].replace("\n", " ")
            raise RuntimeError(f"NVIDIA OpenFold2 HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("NVIDIA OpenFold2 response was not JSON") from error
        pdb_text = _extract_pdb(payload)
        if pdb_text is None or "ATOM" not in pdb_text:
            raise RuntimeError("NVIDIA OpenFold2 response contained no PDB structure")
        return NvidiaHostedOpenFold2Result(
            input_sequence_hash=input_hash,
            pdb_text=pdb_text,
            elapsed_seconds=elapsed_seconds,
            request_artifact_digest=request_digest,
            response_artifact_digest=response_digest,
            limitations=(
                "Hosted structure prediction is a software integration check, not a "
                "validated protein structure.",
                "No multiple sequence alignment or templates were supplied, so accuracy "
                "is lower than a full AlphaFold2-style run.",
                "Per-residue confidence (pLDDT) has not been inspected or thresholded here.",
                "The input protein is not biologically verified to be encoded by any "
                "real organism's genome.",
            ),
        )
