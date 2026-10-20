"""HTTP boundary tests: real gateway/cache/ledger, simulated upstream transports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from concordia.events.sqlite import SQLiteEventLedger
from concordia.genomics.boltz_gateway import BoltzGateway
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzRunner
from concordia.runtime.structure_workflow import create_structure_workflow_app
from concordia.storage.content import ContentAddressedStore

TOKEN = "test-owner-access"
SEQUENCE = "SPEELKGIFEKYAAKEGDPNQLSKEELKLLLQTEFPSLLKGPSTLDELFEELDKNGDGEVSFEEFQVLVKKISQ"
MANIFEST = "ecaa921917627178638397955def230d9bc1563cc4122ac27a099e6f618f25d7"


def setup_client(tmp_path: Path, *, refused: bool = False, status: int = 200):
    calls: list[httpx.Request] = []
    scoring_calls: list[httpx.Request] = []

    def score(request: httpx.Request) -> httpx.Response:
        scoring_calls.append(request)
        body = json.loads(request.content)
        mutation = body["mutations"][0]
        return httpx.Response(
            200,
            json={
                "manifest_digest": MANIFEST,
                "ranker": "ThermoMPNN + one-hot rank average",
                "candidates": []
                if refused
                else [{"candidate": {"variant_id": f"1IGV.pdb_{mutation}"}}],
                "refusals": [
                    {
                        "variant_id": f"1IGV.pdb_{mutation}",
                        "refused": True,
                        "triggers": [
                            {
                                "code": "HARD_PROTECTED_UNIPROT",
                                "evidence": {"accession": "P02633", "uniprot_position": 26},
                            }
                        ],
                    }
                ]
                if refused
                else [],
            },
        )

    def predict(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status,
            json={
                "structures": [{"structure": "TEST STRUCTURE ONLY", "format": "pdb"}],
                "confidence_scores": [0.8],
            },
        )

    runner = NvidiaHostedBoltzRunner(
        ContentAddressedStore(tmp_path / "provider"),
        api_key="test-provider-secret",
        transport=httpx.MockTransport(predict),
    )
    gateway = BoltzGateway(runner, database_path=tmp_path / "quota.sqlite3", global_daily_limit=1)
    app = create_structure_workflow_app(
        state_root=tmp_path,
        sequence=SEQUENCE,
        manifest_digest=MANIFEST,
        access_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
        gateway=gateway,
        scoring_url="https://scorer.test/score",
        scoring_transport=httpx.MockTransport(score),
    )
    return TestClient(app), calls, scoring_calls


def post(client: TestClient, mutation: str = "A13Q") -> httpx.Response:
    return client.post(
        "/structure",
        headers={"authorization": f"Bearer {TOKEN}"},
        json={"mutations": [mutation], "selected_mutation": mutation},
    )


def test_unauthorized_cannot_call_either_model(tmp_path: Path) -> None:
    client, provider, scorer = setup_client(tmp_path)
    result = client.post("/structure", json={"mutations": ["A13Q"], "selected_mutation": "A13Q"})
    assert result.status_code == 401
    assert not provider and not scorer


def test_authenticated_composition_mutates_correct_sequence_and_caches(tmp_path: Path) -> None:
    client, provider, scorer = setup_client(tmp_path)
    result = post(client)
    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "completed"
    assert data["ledger_intact"]
    assert SQLiteEventLedger(tmp_path / "events.sqlite3").verify_chain(data["run_id"]).intact
    payload = json.loads(provider[0].content)
    assert payload["polymers"][0]["sequence"] == SEQUENCE[:12] + "Q" + SEQUENCE[13:]
    assert data["stability"]["ranker"] == "ThermoMPNN + one-hot rank average"
    assert "test-provider-secret" not in result.text and TOKEN not in result.text
    assert post(client).json()["structure"] == data["structure"]
    assert len(provider) == 1 and len(scorer) == 2
    assert post(client, "K6Q").json()["status"] == "rate_limited"
    assert len(provider) == 1


def test_refusals_preserve_evidence_and_never_reach_nvidia(tmp_path: Path) -> None:
    client, provider, _ = setup_client(tmp_path, refused=True)
    data = post(client, "Q21E").json()
    assert data["status"] == "refused"
    assert data["refusals"][0]["triggers"][0]["evidence"]["accession"] == "P02633"
    assert data["ledger_intact"]
    assert not provider


@pytest.mark.parametrize("mutation", ["A0Q", "A75Q", "A13Z", "K13Q"])
def test_invalid_mutations_never_call_models(tmp_path: Path, mutation: str) -> None:
    client, provider, scorer = setup_client(tmp_path)
    assert post(client, mutation).status_code == 422
    assert not provider and not scorer


def test_multi_mutant_cannot_be_forwarded_even_if_upstream_accepts(tmp_path: Path) -> None:
    client, provider, _ = setup_client(tmp_path)
    assert post(client, "A13Q:K6Q").json()["status"] == "refused"
    assert not provider


@pytest.mark.parametrize("status, expected", [(429, "rate_limited"), (500, "unavailable")])
def test_provider_failure_keeps_stability_result(
    tmp_path: Path, status: int, expected: str
) -> None:
    client, provider, _ = setup_client(tmp_path, status=status)
    data = post(client).json()
    assert data["status"] == expected
    assert data["stability"]["candidates"]
    assert data["structure"] is None and data["ledger_intact"]
    assert len(provider) == 1
