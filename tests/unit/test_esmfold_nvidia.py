from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from concordia.genomics.esmfold_nvidia import NvidiaHostedEsmFoldRunner
from concordia.storage.content import ContentAddressedStore

PDB_STUB = (
    "PARENT N/A\n"
    "ATOM      1  N   MET A   1      12.501   2.331 -26.921  1.00 47.72           N  \n"
    "TER\nEND\n"
)


def test_esmfold_prediction_redacts_request_sequence_and_preserves_raw_response(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://health.api.nvidia.com/v1/biology/nvidia/esmfold"
        )
        assert request.headers["authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        assert body["sequence"] == "MKT"
        return httpx.Response(200, json={"pdbs": [PDB_STUB]})

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    result = NvidiaHostedEsmFoldRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    ).predict("mkt")

    assert result.pdb_text == PDB_STUB
    assert not result.scientific_use_allowed
    retained_request = json.loads(artifacts.get_bytes(result.request_artifact_digest))
    assert retained_request["input_retained"] is False
    assert retained_request["input_sequence_length"] == 3
    assert "MKT" not in json.dumps(retained_request)
    assert artifacts.get_bytes(result.response_artifact_digest)
    assert "test-secret" not in result.model_dump_json()


def test_esmfold_rejects_invalid_amino_acids_before_any_request(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request should be made for invalid input")

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedEsmFoldRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ValueError, match="standard amino acids"):
        runner.predict("BJOUZ")  # not standard single-letter amino acid codes


def test_esmfold_requires_api_key(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NvidiaHostedEsmFoldRunner(artifacts, api_key="").predict("MKT")


def test_esmfold_surfaces_retirement_distinctly(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410, json={"detail": "gone"})

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedEsmFoldRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match="retired"):
        runner.predict("MKT")


def test_esmfold_fails_closed_on_missing_pdb_field(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedEsmFoldRunner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match="no PDB structure"):
        runner.predict("MKT")
