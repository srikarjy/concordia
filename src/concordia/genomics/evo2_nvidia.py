"""Optional NVIDIA-hosted Evo2 forward runner with immutable raw tensors."""

from __future__ import annotations

import base64
import binascii
import io
import os
import zipfile
from typing import Any

import httpx
import numpy as np

from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore


class NvidiaHostedEvo2Runner:
    """Compute a declared likelihood target from NVIDIA's real Evo2 7B logits."""

    checkpoint = "arc/evo2-7b-forward"
    endpoint = "https://health.api.nvidia.com/v1/biology/arc/evo2-7b/forward"
    target = "mean_next_base_log_likelihood"
    max_encoded_bytes = 192 * 1024 * 1024
    max_uncompressed_bytes = 256 * 1024 * 1024

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

    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, Any]:
        if checkpoint != self.checkpoint:
            raise ValueError(f"hosted runner supports only {self.checkpoint}")
        if target != self.target:
            raise ValueError(f"hosted runner supports only {self.target}")
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY is required for hosted Evo2 forward inference")

        request_payload = {"sequence": sequence.sequence, "output_layers": ["output_layer"]}
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "checkpoint": checkpoint,
                "target": target,
                "endpoint": self.endpoint,
                "request": request_payload,
            }
        )
        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self._transport,
        ) as client:
            response = client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=request_payload,
            )
        response.raise_for_status()
        payload = response.json()
        encoded = payload.get("data")
        if not isinstance(encoded, str):
            raise RuntimeError("NVIDIA Evo2 response did not contain encoded forward tensors")
        if len(encoded) > self.max_encoded_bytes:
            raise RuntimeError("NVIDIA Evo2 tensor response exceeded the configured limit")
        try:
            tensor_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise RuntimeError("NVIDIA Evo2 tensor payload was not valid base64") from error
        tensor_digest = self.artifacts.put_bytes(tensor_bytes)
        logits = self._load_output_logits(tensor_bytes, len(sequence.sequence))
        score = self._mean_next_base_log_likelihood(logits, sequence.sequence)
        return {
            "model_id": checkpoint,
            "execution_mode": "real",
            "sequence_hash": sequence.content_hash(),
            "score": score,
            "target": target,
            "scientific_use_allowed": True,
            "input_artifact_digest": request_digest,
            "output_artifact_digest": tensor_digest,
            "runtime_metadata": {
                "provider": "nvidia",
                "endpoint": self.endpoint,
                "elapsed_ms": payload.get("elapsed_ms"),
                "output_layer": "output_layer",
                "scoring_version": "mean-next-base-log-likelihood-v1",
            },
        }

    @staticmethod
    def _load_output_logits(tensor_bytes: bytes, sequence_length: int) -> np.ndarray:
        try:
            with zipfile.ZipFile(io.BytesIO(tensor_bytes)) as bundle:
                if sum(item.file_size for item in bundle.infolist()) > (
                    NvidiaHostedEvo2Runner.max_uncompressed_bytes
                ):
                    raise RuntimeError("Evo2 tensor archive exceeded the uncompressed limit")
            with np.load(io.BytesIO(tensor_bytes), allow_pickle=False) as archive:
                names = archive.files
                if "output_layer" in names:
                    raw = archive["output_layer"]
                elif len(names) == 1:
                    raw = archive[names[0]]
                else:
                    raise RuntimeError("forward tensor archive has no unambiguous output layer")
                logits = np.asarray(raw, dtype=np.float64)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError("NVIDIA Evo2 forward tensor archive is invalid") from error

        if logits.ndim == 3 and logits.shape[1] == 1:
            logits = logits[:, 0, :]
        elif logits.ndim == 3 and logits.shape[0] == 1:
            logits = logits[0, :, :]
        if logits.ndim != 2 or logits.shape[0] != sequence_length or logits.shape[1] != 512:
            raise RuntimeError(
                "Evo2 output_layer must have shape [sequence_length, 1, 512]"
            )
        if not np.isfinite(logits).all():
            raise RuntimeError("Evo2 output logits contain non-finite values")
        return logits

    @staticmethod
    def _mean_next_base_log_likelihood(logits: np.ndarray, sequence: str) -> float:
        if len(sequence) < 2:
            raise ValueError("likelihood scoring requires at least two nucleotides")
        target_indices = np.fromiter((ord(base) for base in sequence[1:]), dtype=np.int64)
        predictions = logits[:-1]
        maxima = predictions.max(axis=1)
        log_denominator = maxima + np.log(
            np.exp(predictions - maxima[:, np.newaxis]).sum(axis=1)
        )
        selected = predictions[np.arange(len(target_indices)), target_indices]
        return float(np.mean(selected - log_denominator))
