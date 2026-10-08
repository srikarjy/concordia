from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from concordia.genomics.boltz_nvidia import BoltzComplexRequest, NvidiaHostedBoltzRunner
from concordia.storage.content import ContentAddressedStore

STRUCTURE_STUB = "ATOM      1  N   MET A   1      12.501   2.331 -26.921  1.00 47.72      N\n"


def test_boltz_synchronous_200_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://health.api.nvidia.com/v1/biology/mit/boltz2/predict"
        )
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.headers["nvcf-poll-seconds"] == "300"
        body = json.loads(request.content)
        assert body["polymers"][0]["sequence"] == "MKT"
        assert "ligands" not in body
        return httpx.Response(
            200,
            json={
                "structures": [{"format": "pdb", "structure": STRUCTURE_STUB}],
                "confidence_scores": [0.87],
            },
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    result = NvidiaHostedBoltzRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    ).predict("mkt")

    assert result.structure_text == STRUCTURE_STUB
    assert result.structure_format == "pdb"
    assert result.confidence_scores == (0.87,)
    assert not result.scientific_use_allowed
    assert "test-secret" not in result.model_dump_json()
    retained_request = json.loads(artifacts.get_bytes(result.request_artifact_digest))
    assert retained_request["input_retained"] is False
    assert retained_request["input_sequence_length"] == 3
    assert "MKT" not in json.dumps(retained_request)


def test_boltz_async_202_then_polls_to_completion(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"nvcf-reqid": "task-123"}, json={})
        assert request.url == httpx.URL(
            "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/task-123"
        )
        calls["count"] += 1
        if calls["count"] < 2:
            return httpx.Response(202, json={})
        return httpx.Response(
            200,
            json={"structures": [{"format": "pdb", "structure": STRUCTURE_STUB}]},
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedBoltzRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    runner.poll_interval_seconds = 0.0
    result = runner.predict("MKT")

    assert result.structure_text == STRUCTURE_STUB
    assert calls["count"] == 2


def test_boltz_poll_exhaustion_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"nvcf-reqid": "task-999"}, json={})
        return httpx.Response(202, json={})

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedBoltzRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    runner.poll_interval_seconds = 0.0
    runner.max_poll_attempts = 3
    with pytest.raises(RuntimeError, match="did not complete within the polling budget"):
        runner.predict("MKT")


def test_boltz_rejects_invalid_amino_acids(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request should be made for invalid input")

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedBoltzRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ValueError, match="standard amino acids"):
        runner.predict("BJOUZ")


def test_boltz_requires_api_key(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NvidiaHostedBoltzRunner(artifacts, api_key="").predict("MKT")


def test_boltz_complex_sends_multiple_polymers_and_retains_bounded_provenance(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert [polymer["id"] for polymer in body["polymers"]] == ["H", "L", "A"]
        assert body["polymers"][0]["sequence"] == "EVQLV"
        assert body["polymers"][2]["molecule_type"] == "protein"
        assert body["polymers"][0]["msa"]["uniref90"]["a3m"]["format"] == "a3m"
        return httpx.Response(
            200,
            json={"structures": [{"format": "mmcif", "structure": STRUCTURE_STUB}]},
        )

    request = BoltzComplexRequest(
        polymers=(
            {"id": "H", "molecule_type": "protein", "sequence": "EVQLV"},
            {"id": "L", "molecule_type": "protein", "sequence": "DIQMT"},
            {"id": "A", "molecule_type": "protein", "sequence": "MKTAY"},
        )
    )
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    result = NvidiaHostedBoltzRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    ).predict_complex(request)

    assert result.structure_format == "mmcif"
    assert result.execution_mode == "real_hosted_complex_structure_prediction"
    assert result.scientific_use_allowed is False
    retained_request = json.loads(artifacts.get_bytes(result.request_artifact_digest))
    assert retained_request["polymer_count"] == 3
    assert "EVQLV" not in json.dumps(retained_request)


def test_boltz_complex_rejects_duplicate_chain_ids() -> None:
    with pytest.raises(ValueError, match="IDs must be unique"):
        BoltzComplexRequest(
            polymers=(
                {"id": "A", "sequence": "MKT"},
                {"id": "A", "sequence": "EVQ"},
            )
        )
