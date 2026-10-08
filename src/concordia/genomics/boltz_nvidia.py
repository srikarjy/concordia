"""NVIDIA-hosted Boltz-2 structure prediction.

The runner supports the original single-chain path and a separately typed
multi-chain path for antibody-antigen complexes. Both paths retain bounded
request/response artifacts and explicitly remain computational outputs, not
validated biological evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from concordia.storage.content import ContentAddressedStore

SHA256_PATTERN = r"^[0-9a-f]{64}$"
AMINO_ACID_PATTERN = r"^[ARNDCQEGHILKMFPSTWYV]+$"


class NvidiaHostedBoltzResult(BaseModel):
    """Validated single-chain output that is never scientific evidence."""

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


class BoltzPolymer(BaseModel):
    """A structured polymer accepted by the Boltz-2 NIM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=4, pattern=r"^[A-Za-z0-9]+$")
    molecule_type: Literal["protein", "dna", "rna"] = "protein"
    sequence: str = Field(min_length=1, max_length=4_096)
    msa: dict[str, Any] | None = None

    @field_validator("sequence")
    @classmethod
    def normalize_sequence(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        if not normalized:
            raise ValueError("polymer sequence must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_alphabet(self) -> BoltzPolymer:
        allowed = {
            "protein": set("ARNDCQEGHILKMFPSTWYV"),
            "dna": set("ACGT"),
            "rna": set("ACGU"),
        }[self.molecule_type]
        invalid = sorted(set(self.sequence) - allowed)
        if invalid:
            raise ValueError(
                f"{self.molecule_type} polymer contains unsupported residues: "
                + "".join(invalid)
            )
        return self


class BoltzComplexRequest(BaseModel):
    """Validated multi-chain input for antibody-antigen prediction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    polymers: tuple[BoltzPolymer, ...] = Field(min_length=2, max_length=12)
    recycling_steps: int = Field(default=1, ge=1, le=10)
    sampling_steps: int = Field(default=20, ge=1, le=200)
    diffusion_samples: int = Field(default=1, ge=1, le=5)
    step_scale: float = Field(default=1.2, gt=0, le=3)
    without_potentials: bool = True

    @model_validator(mode="after")
    def validate_polymers(self) -> BoltzComplexRequest:
        ids = [polymer.id for polymer in self.polymers]
        if len(set(ids)) != len(ids):
            raise ValueError("Boltz polymer IDs must be unique")
        return self


class NvidiaHostedBoltzComplexResult(BaseModel):
    """Validated multi-chain output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["mit/boltz2"] = "mit/boltz2"
    execution_mode: Literal["real_hosted_complex_structure_prediction"] = (
        "real_hosted_complex_structure_prediction"
    )
    input_payload_hash: str = Field(pattern=SHA256_PATTERN)
    structure_text: str = Field(min_length=1)
    structure_format: str = Field(min_length=1)
    confidence_scores: tuple[float, ...] = Field(default_factory=tuple)
    elapsed_seconds: float = Field(ge=0)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    response_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class NvidiaHostedBoltzRunner:
    """Call NVIDIA's hosted Boltz-2 NIM, including async NVCF polling."""

    model_id = "mit/boltz2"
    endpoint = "https://health.api.nvidia.com/v1/biology/mit/boltz2/predict"
    status_endpoint_template = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/{task_id}"
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
                + "".join(invalid)
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
        submitted = self._submit(
            request_payload,
            input_hash=input_hash,
            request_metadata={
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
            },
        )
        structure_text, structure_format, confidence_scores = self._parse_response(
            submitted["payload"]
        )
        return NvidiaHostedBoltzResult(
            input_sequence_hash=input_hash,
            structure_text=structure_text,
            structure_format=structure_format,
            confidence_scores=confidence_scores,
            elapsed_seconds=submitted["elapsed_seconds"],
            request_artifact_digest=submitted["request_digest"],
            response_artifact_digest=submitted["response_digest"],
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

    def predict_complex(
        self, request: BoltzComplexRequest
    ) -> NvidiaHostedBoltzComplexResult:
        """Predict an antibody-antigen or other multi-chain complex."""

        payload = request.model_dump(mode="json", exclude_none=True)
        for polymer in payload["polymers"]:
            if polymer["molecule_type"] == "protein" and "msa" not in polymer:
                polymer["msa"] = {
                    "uniref90": {
                        "a3m": {
                            "alignment": f">seq1\n{polymer['sequence']}",
                            "format": "a3m",
                        }
                    }
                }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        input_hash = hashlib.sha256(canonical).hexdigest()
        submitted = self._submit(
            payload,
            input_hash=input_hash,
            request_metadata={
                "input_payload_hash": input_hash,
                "polymer_count": len(request.polymers),
                "polymer_ids": [polymer.id for polymer in request.polymers],
                "request_parameters": {
                    "recycling_steps": request.recycling_steps,
                    "sampling_steps": request.sampling_steps,
                    "diffusion_samples": request.diffusion_samples,
                    "step_scale": request.step_scale,
                    "without_potentials": request.without_potentials,
                },
                "input_retained": False,
                "scientific_use_allowed": False,
            },
        )
        structure_text, structure_format, confidence_scores = self._parse_response(
            submitted["payload"]
        )
        return NvidiaHostedBoltzComplexResult(
            input_payload_hash=input_hash,
            structure_text=structure_text,
            structure_format=structure_format,
            confidence_scores=confidence_scores,
            elapsed_seconds=submitted["elapsed_seconds"],
            request_artifact_digest=submitted["request_digest"],
            response_artifact_digest=submitted["response_digest"],
            limitations=(
                "Hosted complex prediction is a computational structure hypothesis, not "
                "validated affinity or therapeutic evidence.",
                "Antibody numbering and CDR boundaries were not inferred by this call.",
                "Interface confidence and clashes have not been independently assessed.",
            ),
        )

    def _submit(
        self,
        request_payload: dict[str, Any],
        *,
        input_hash: str,
        request_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted Boltz-2 prediction")
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_hash": input_hash,
                **request_metadata,
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
        return {
            "payload": payload,
            "elapsed_seconds": elapsed_seconds,
            "request_digest": request_digest,
            "response_digest": response_digest,
        }

    @staticmethod
    def _parse_response(payload: Any) -> tuple[str, str, tuple[float, ...]]:
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
        return structure_text, structure_format or "pdb", confidence_scores

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
