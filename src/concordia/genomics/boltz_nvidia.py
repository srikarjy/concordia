"""NVIDIA-hosted Boltz-2 protein structure prediction.

Replaces ESMFold (``esmfold_nvidia.py``) as the live structure-prediction
backend: NVIDIA's own catalog page confirms ESMFold (``nvidia/esmfold``) no
longer resolves for a real account (``404: Function not found``), while
Boltz-2 does. Endpoint, request schema, and the async NVCF polling protocol
are taken from NVIDIA's own published sample code at
``https://build.nvidia.com/mit/boltz2`` (fetched 2026-10-02), not guessed.

Only single-chain, ligand-free protein folding is requested here. Boltz-2
requires an MSA input; this module sends the official sample's own
simplification — a one-sequence "alignment" containing just the query
itself — which is not a real multiple sequence alignment.
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


class NvidiaHostedBoltzResult(BaseModel):
    """Validated structure-prediction output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["mit/boltz2"] = "mit/boltz2"
    execution_mode: Literal["real_hosted_structure_prediction"] = (
        "real_hosted_structure_prediction"
    )
    input_sequence_hash: str = Field(pattern=SHA256_PATTERN)
    structure_text: str = Field(min_length=1)
    structure_format: str = Field(min_length=1)
    confidence_scores: tuple[float, ...] = Field(default_factory=tuple)
    elapsed_seconds: float = Field(ge=0)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    response_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class NvidiaHostedBoltzRunner:
    """Call NVIDIA's hosted Boltz-2 NIM, including its async NVCF polling path."""

    model_id = "mit/boltz2"
    endpoint = "https://health.api.nvidia.com/v1/biology/mit/boltz2/predict"
    status_endpoint_template = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/{task_id}"
    # NVIDIA's current Boltz-2 NIM contract allows 1-4,096 residues per polymer.
    max_sequence_length = 4_096
    poll_seconds_header = 300
    max_poll_attempts = 60
    poll_interval_seconds = 5.0
    max_response_bytes = 32 * 1024 * 1024

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 320.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.artifacts = artifacts
        self._api_key = os.environ.get("NVIDIA_API_KEY") if api_key is None else api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def predict(
        self,
        sequence: str,
        *,
        recycling_steps: int = 1,
        sampling_steps: int = 20,
        diffusion_samples: int = 1,
        step_scale: float = 1.2,
    ) -> NvidiaHostedBoltzResult:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted Boltz-2 prediction")
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
        request_payload = {
            "polymers": [
                {
                    "id": "A",
                    "molecule_type": "protein",
                    "sequence": normalized,
                    "msa": {
                        "uniref90": {
                            "a3m": {
                                "alignment": f">seq1\n{normalized}",
                                "format": "a3m",
                            }
                        }
                    },
                }
            ],
            "recycling_steps": recycling_steps,
            "sampling_steps": sampling_steps,
            "diffusion_samples": diffusion_samples,
            "step_scale": step_scale,
            "without_potentials": True,
        }
        input_hash = hashlib.sha256(normalized.encode("ascii")).hexdigest()
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_sequence_hash": input_hash,
                "input_sequence_length": len(normalized),
                "request_parameters": {
                    "recycling_steps": recycling_steps,
                    "sampling_steps": sampling_steps,
                    "diffusion_samples": diffusion_samples,
                    "step_scale": step_scale,
                    "without_potentials": True,
                    "polymer_count": 1,
                    "molecule_type": "protein",
                    "msa_method": "single_sequence_self_reference",
                },
                "input_retained": False,
                "scientific_use_allowed": False,
            }
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "NVCF-POLL-SECONDS": str(self.poll_seconds_header),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        started = time.monotonic()
        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            response = client.post(self.endpoint, headers=headers, json=request_payload)
            if response.status_code == 202:
                task_id = response.headers.get("nvcf-reqid")
                if not task_id:
                    raise RuntimeError(
                        "NVIDIA Boltz-2 accepted the job but returned no nvcf-reqid to poll"
                    )
                response = self._poll_status(client, headers, task_id)
        elapsed_seconds = time.monotonic() - started
        if len(response.content) > self.max_response_bytes:
            raise RuntimeError("NVIDIA Boltz-2 response exceeded the configured limit")
        response_digest = self.artifacts.put_bytes(response.content)
        if response.is_error:
            detail = response.text[:1_000].replace("\n", " ")
            raise RuntimeError(f"NVIDIA Boltz-2 HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("NVIDIA Boltz-2 response was not JSON") from error
        structures = payload.get("structures")
        if not isinstance(structures, list) or not structures:
            raise RuntimeError("NVIDIA Boltz-2 response contained no structure")
        first = structures[0]
        structure_text = first.get("structure") if isinstance(first, dict) else None
        structure_format = first.get("format") if isinstance(first, dict) else None
        if not isinstance(structure_text, str) or not structure_text:
            raise RuntimeError("NVIDIA Boltz-2 structure entry had no structure text")
        confidence_raw = payload.get("confidence_scores") or []
        confidence_scores = tuple(
            float(value) for value in confidence_raw if isinstance(value, int | float)
        )
        return NvidiaHostedBoltzResult(
            input_sequence_hash=input_hash,
            structure_text=structure_text,
            structure_format=structure_format or "pdb",
            confidence_scores=confidence_scores,
            elapsed_seconds=elapsed_seconds,
            request_artifact_digest=request_digest,
            response_artifact_digest=response_digest,
            limitations=(
                "Hosted structure prediction is a software integration check, not a "
                "validated protein structure.",
                "The MSA sent is a one-sequence self-reference, not a real multiple "
                "sequence alignment, which measurably reduces Boltz-2 accuracy.",
                "Per-residue confidence has not been inspected or thresholded here.",
                "The input protein is not biologically verified to be encoded by any "
                "real organism's genome.",
            ),
        )

    def _poll_status(
        self, client: httpx.Client, headers: dict[str, str], task_id: str
    ) -> httpx.Response:
        status_url = self.status_endpoint_template.format(task_id=task_id)
        for _ in range(self.max_poll_attempts):
            response = client.get(status_url, headers=headers)
            if response.status_code == 200:
                return response
            if response.status_code != 202:
                return response
            time.sleep(self.poll_interval_seconds)
        raise RuntimeError(
            f"NVIDIA Boltz-2 task {task_id} did not complete within the polling budget"
        )
