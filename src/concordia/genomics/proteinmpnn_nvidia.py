"""NVIDIA-hosted ProteinMPNN inverse folding.

ProteinMPNN reads a backbone and proposes sequences likely to fold into it. In a
binder design loop it follows RFdiffusion (see ``rfdiffusion_nvidia.py``) and
feeds a structure predictor, which re-folds the proposed sequence so the design
can be checked against the backbone it was meant to reproduce.

``input_pdb_chains`` matters for binder design: without it every chain is
redesigned, including the target, which is not what a binder campaign wants.

The NIM also returns per-position amino-acid probabilities. Those stay in the
content-addressed response artifact rather than the result model, which keeps a
bounded output in line with the Evo 2 attribution adapter.
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
# Designed multi-chain sequences are returned with '/' between chains.
DESIGNED_SEQUENCE_PATTERN = r"^[ARNDCQEGHILKMFPSTWYVX/]+$"


class ProteinMpnnRequest(BaseModel):
    """Validated inverse-folding input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_pdb: str = Field(min_length=1, max_length=4_000_000)
    # Omitted means every chain is redesigned, which is rarely what a binder run wants.
    design_chains: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    num_sequences: int = Field(default=1, ge=1, le=16)
    sampling_temperature: float = Field(default=0.1, gt=0, le=1)
    ca_only: bool = False
    use_soluble_model: bool = False
    random_seed: int | None = Field(default=None, ge=0)
    fixed_positions_jsonl: str | None = Field(default=None, max_length=100_000)

    @field_validator("design_chains")
    @classmethod
    def validate_chains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        invalid = [item for item in value if not re.fullmatch(r"^[A-Za-z0-9]{1,4}$", item)]
        if invalid:
            raise ValueError(f"chain identifiers must be alphanumeric, got: {', '.join(invalid)}")
        if len(set(value)) != len(value):
            raise ValueError("chain identifiers must be unique")
        return value


class DesignedSequence(BaseModel):
    """One sequence proposed for the input backbone."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    sequence: str = Field(min_length=1, pattern=DESIGNED_SEQUENCE_PATTERN)
    # ProteinMPNN's own log-probability for this sequence; lower is a worse fit to
    # the backbone. It says nothing about binding, expression or stability.
    score: float | None = None
    header: str = Field(default="", max_length=500)


class NvidiaHostedProteinMpnnResult(BaseModel):
    """Validated inverse-folding output that is never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: Literal["ipd/proteinmpnn"] = "ipd/proteinmpnn"
    execution_mode: Literal["real_hosted_inverse_folding"] = "real_hosted_inverse_folding"
    input_payload_hash: str = Field(pattern=SHA256_PATTERN)
    designed_sequences: tuple[DesignedSequence, ...] = Field(min_length=1)
    design_chains: tuple[str, ...] = Field(default_factory=tuple)
    sampling_temperature: float = Field(gt=0, le=1)
    elapsed_seconds: float = Field(ge=0)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    response_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


def parse_mfasta(text: str) -> tuple[tuple[str, str], ...]:
    """Split multi-FASTA into (header, sequence) pairs, preserving order."""
    records: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            records.append((stripped[1:], []))
        elif records:
            records[-1][1].append(stripped)
    return tuple((header, "".join(parts)) for header, parts in records if parts)


def _score_from_header(header: str) -> float | None:
    """ProteinMPNN writes 'score=1.234' into each FASTA header."""
    found = re.search(r"\bscore=(-?\d+(?:\.\d+)?)", header)
    return float(found.group(1)) if found else None


class NvidiaHostedProteinMpnnRunner:
    """Call NVIDIA's hosted ProteinMPNN NIM and preserve exact request/response bytes."""

    model_id = "ipd/proteinmpnn"
    endpoint = "https://health.api.nvidia.com/v1/biology/ipd/proteinmpnn/predict"
    max_response_bytes = 32 * 1024 * 1024

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

    def preflight(self) -> None:
        """Reject requests that can never succeed, so a gateway spends no quota on them."""
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted ProteinMPNN inference")

    def design(self, request: ProteinMpnnRequest) -> NvidiaHostedProteinMpnnResult:
        self.preflight()
        body: dict[str, object] = {
            "input_pdb": request.input_pdb,
            "num_seq_per_target": request.num_sequences,
            "sampling_temp": [request.sampling_temperature],
            "ca_only": request.ca_only,
            "use_soluble_model": request.use_soluble_model,
        }
        if request.design_chains:
            body["input_pdb_chains"] = list(request.design_chains)
        if request.random_seed is not None:
            body["random_seed"] = request.random_seed
        if request.fixed_positions_jsonl is not None:
            body["fixed_positions_jsonl"] = request.fixed_positions_jsonl
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        input_hash = hashlib.sha256(canonical).hexdigest()
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "model_id": self.model_id,
                "endpoint": self.endpoint,
                "input_payload_hash": input_hash,
                "input_pdb_bytes": len(request.input_pdb),
                "request_parameters": {
                    "design_chains": list(request.design_chains),
                    "num_sequences": request.num_sequences,
                    "sampling_temperature": request.sampling_temperature,
                    "ca_only": request.ca_only,
                    "use_soluble_model": request.use_soluble_model,
                    "random_seed": request.random_seed,
                    "fixed_positions_jsonl": request.fixed_positions_jsonl,
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
            raise RuntimeError("NVIDIA ProteinMPNN response exceeded the configured limit")
        response_digest = self.artifacts.put_bytes(response.content)
        if response.is_error:
            # Upstream detail goes to the server log, not to the (public) caller.
            _log.warning(
                "NVIDIA ProteinMPNN HTTP %s: %s",
                response.status_code,
                response.text[:1_000].replace("\n", " "),
            )
            raise RuntimeError(f"NVIDIA ProteinMPNN HTTP {response.status_code}")
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("NVIDIA ProteinMPNN response was not JSON") from error
        mfasta = payload.get("mfasta") if isinstance(payload, dict) else None
        if not isinstance(mfasta, str) or not mfasta.strip():
            raise RuntimeError("NVIDIA ProteinMPNN response contained no sequences")
        scores = payload.get("scores") if isinstance(payload, dict) else None
        records = parse_mfasta(mfasta)
        if not records:
            raise RuntimeError("NVIDIA ProteinMPNN multi-FASTA contained no records")
        designed: list[DesignedSequence] = []
        for index, (header, sequence) in enumerate(records):
            score = _score_from_header(header)
            if score is None and isinstance(scores, list) and index < len(scores):
                candidate = scores[index]
                if isinstance(candidate, int | float) and not isinstance(candidate, bool):
                    score = float(candidate)
            designed.append(
                DesignedSequence(sequence=sequence.upper(), score=score, header=header[:500])
            )
        return NvidiaHostedProteinMpnnResult(
            input_payload_hash=input_hash,
            designed_sequences=tuple(designed),
            design_chains=request.design_chains,
            sampling_temperature=request.sampling_temperature,
            elapsed_seconds=elapsed_seconds,
            request_artifact_digest=request_digest,
            response_artifact_digest=response_digest,
            limitations=(
                "An inverse-folding score is the model's own fit to the backbone it was "
                "given. It is not a measure of binding, stability or expression.",
                "The first record of a ProteinMPNN multi-FASTA is normally the input "
                "sequence, not a design; check the headers before using one.",
                "A sequence proposed for a backbone is not evidence that it folds into it. "
                "Confirm with an independent structure prediction.",
                "Per-position probabilities are not returned here; they remain in the "
                "response artifact.",
            ),
        )
