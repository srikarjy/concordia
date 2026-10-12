from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from concordia.genomics.openfold2_nvidia import NvidiaHostedOpenFold2Runner
from concordia.storage.content import ContentAddressedStore

PDB_STUB = "ATOM      1  N   MET A   1      12.501   2.331 -26.921  1.00 47.72           N  \nEND\n"


def _runner(
    tmp_path: Path, handler: object
) -> tuple[NvidiaHostedOpenFold2Runner, ContentAddressedStore]:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = NvidiaHostedOpenFold2Runner(
        artifacts, api_key="test-secret", transport=httpx.MockTransport(handler)  # type: ignore[arg-type]
    )
    return runner, artifacts


def test_openfold2_parses_ranked_structures_and_redacts_sequence(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-secret"
        assert json.loads(request.content) == {"sequence": "MKT"}
        return httpx.Response(
            200, json={"structures_in_ranked_order": [{"format": "pdb", "structure": PDB_STUB}]}
        )

    runner, artifacts = _runner(tmp_path, handler)
    result = runner.predict("mkt")

    assert result.pdb_text == PDB_STUB
    assert not result.scientific_use_allowed
    retained = json.loads(artifacts.get_bytes(result.request_artifact_digest))
    assert retained["input_retained"] is False
    assert "MKT" not in json.dumps(retained)
    assert "test-secret" not in result.model_dump_json()


def test_openfold2_rejects_invalid_residues_before_any_request(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent")

    runner, _ = _runner(tmp_path, handler)
    with pytest.raises(ValueError, match="standard amino acids"):
        runner.predict("BJOUZ")


def test_openfold2_surfaces_retirement_and_missing_structure(tmp_path: Path) -> None:
    runner, _ = _runner(tmp_path, lambda r: httpx.Response(410, json={}))
    with pytest.raises(RuntimeError, match="retired"):
        runner.predict("MKT")
    runner, _ = _runner(tmp_path, lambda r: httpx.Response(200, json={"other": 1}))
    with pytest.raises(RuntimeError, match="no PDB structure"):
        runner.predict("MKT")


def test_openfold2_requires_api_key(tmp_path: Path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NvidiaHostedOpenFold2Runner(artifacts, api_key="").predict("MKT")
