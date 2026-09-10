from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from concordia.genomics.evo2_nvidia import (
    NvidiaHostedEvo2GenerationRunner,
    NvidiaHostedEvo2Runner,
)
from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore

ROOT = Path(__file__).resolve().parents[2]


def sequence() -> GenomicSequence:
    return GenomicSequence(
        sequence_id="synthetic:nvidia-smoke",
        sequence="ACGT",
        assembly="synthetic",
        region="synthetic:0-4",
        strand="+",
    )


def test_nvidia_generation_preserves_request_and_raw_response(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://health.api.nvidia.com/v1/biology/arc/evo2-40b/generate"
        )
        assert request.headers["authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        assert body["sequence"] == "ACGT"
        assert body["enable_logits"] is False
        return httpx.Response(
            200,
            json={
                "sequence": "TGCA",
                "sampled_probs": [0.9, 0.8, 0.7, 0.6],
                "elapsed_ms": 12,
                "elapsed_ms_per_token": [3, 3, 3, 3],
                "logits": None,
            },
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    result = NvidiaHostedEvo2GenerationRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    ).generate(sequence(), num_tokens=4)

    assert result.generated_sequence == "TGCA"
    assert result.sampled_probabilities == (0.9, 0.8, 0.7, 0.6)
    assert not result.scientific_use_allowed
    assert artifacts.get_bytes(result.request_artifact_digest)
    assert artifacts.get_bytes(result.response_artifact_digest)
    assert "test-secret" not in result.model_dump_json()


def test_nvidia_generation_fails_closed_on_invalid_output_or_missing_key(tmp_path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NvidiaHostedEvo2GenerationRunner(artifacts, api_key="").generate(sequence())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"sequence": "NN", "sampled_probs": [0.5, 0.5], "elapsed_ms": 1},
        )

    with pytest.raises(RuntimeError, match="unexpected DNA"):
        NvidiaHostedEvo2GenerationRunner(
            artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
        ).generate(sequence(), num_tokens=2)


def test_nvidia_hosted_forward_route_is_never_called(tmp_path) -> None:
    runner = NvidiaHostedEvo2Runner(ContentAddressedStore(tmp_path / "artifacts"))
    with pytest.raises(RuntimeError, match="generation only"):
        runner.score(
            sequence(),
            checkpoint="arc/evo2-7b-forward",
            target="mean_next_base_log_likelihood",
        )


def test_committed_hosted_smoke_record_is_not_scientific_evidence() -> None:
    report = json.loads(
        (ROOT / "reports/nvidia-evo2-hosted-smoke.json").read_text(encoding="utf-8")
    )

    assert report["execution_mode"] == "real_hosted_generation"
    assert report["scientific_use_allowed"] is False
    assert report["input"]["assembly"] == "synthetic"
    assert report["endpoint"].endswith("/generate")
    assert len(report["request_artifact_digest"]) == 64
    assert len(report["response_artifact_digest"]) == 64
