from __future__ import annotations

import base64
import io
import json

import httpx
import numpy as np
import pytest

from concordia.genomics.evo2_nvidia import NvidiaHostedEvo2Runner
from concordia.genomics.evo2_real import RealEvo2Scorer
from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore


def sequence() -> GenomicSequence:
    return GenomicSequence(
        sequence_id="chr11:0-4",
        sequence="ACGT",
        assembly="GRCh38",
        region="chr11:0-4",
        strand="+",
    )


def encoded_logits() -> str:
    logits = np.zeros((4, 1, 512), dtype=np.float32)
    logits[0, 0, ord("C")] = 4
    logits[1, 0, ord("G")] = 4
    logits[2, 0, ord("T")] = 4
    output = io.BytesIO()
    np.savez(output, output_layer=logits)
    return base64.b64encode(output.getvalue()).decode("ascii")


def test_nvidia_runner_preserves_request_and_raw_tensor_artifacts(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-secret"
        assert json.loads(request.content)["output_layers"] == ["output_layer"]
        return httpx.Response(200, json={"data": encoded_logits(), "elapsed_ms": 12})

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedEvo2Runner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    scorer = RealEvo2Scorer(
        runner,
        checkpoint="arc/evo2-7b-forward",
        target="mean_next_base_log_likelihood",
    )

    result = scorer.score(sequence())

    assert result.execution_mode == "real"
    assert result.score < 0
    assert result.input_artifact_digest is not None
    assert result.output_artifact_digest is not None
    assert artifacts.get_bytes(result.input_artifact_digest)
    assert artifacts.get_bytes(result.output_artifact_digest)
    assert "test-secret" not in json.dumps(result.model_dump(mode="json"))


def test_nvidia_runner_fails_closed_without_key_or_on_wrong_scope(tmp_path) -> None:
    runner = NvidiaHostedEvo2Runner(ContentAddressedStore(tmp_path / "artifacts"), api_key="")
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        runner.score(
            sequence(),
            checkpoint="arc/evo2-7b-forward",
            target="mean_next_base_log_likelihood",
        )
    keyed = NvidiaHostedEvo2Runner(
        ContentAddressedStore(tmp_path / "other"), api_key="test-secret"
    )
    with pytest.raises(ValueError, match="supports only"):
        keyed.score(sequence(), checkpoint="evo2-40b", target=keyed.target)
