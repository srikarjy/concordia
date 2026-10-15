"""Regression tests for the public workspace API's abuse and integrity boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concordia.api.workspace import create_workspace_app
from concordia.experiments import service as experiment_service

TOKEN_HEADER = "X-Concordia-Experiment-Token"
DNA_ROOT = {
    "kind": "dna_sequence",
    "operation": "root",
    "label": "reference",
    "payload": {"payload_type": "dna", "sequence": "ACGTACGT"},
}


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    monkeypatch.delenv("CONCORDIA_DATABASE_URL", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))


def _new_experiment(client: TestClient, headers: dict[str, str] | None = None) -> tuple[str, dict]:
    response = client.post("/experiments", json={"title": "security"}, headers=headers or {})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["experiment"]["experiment_id"], {TOKEN_HEADER: body["access_token"]}


def test_client_cannot_self_certify_scientific_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    experiment_id, auth = _new_experiment(client)
    rejected = client.post(
        f"/experiments/{experiment_id}/nodes",
        json={**DNA_ROOT, "scientific_use_allowed": True},
        headers=auth,
    )
    assert rejected.status_code == 422
    assert "cannot be set by clients" in rejected.json()["detail"]
    accepted = client.post(f"/experiments/{experiment_id}/nodes", json=DNA_ROOT, headers=auth)
    assert accepted.status_code == 200
    assert accepted.json()["scientific_use_allowed"] is False


def test_spoofed_leftmost_forwarded_for_does_not_evade_creation_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, CONCORDIA_TRUST_PROXY_HEADERS="1")
    statuses = []
    for index in range(12):
        # The proxy appends the real peer last; everything before it is attacker-controlled.
        headers = {"X-Forwarded-For": f"10.9.9.{index}, 203.0.113.7"}
        response = client.post("/experiments", json={"title": "x"}, headers=headers)
        statuses.append(response.status_code)
    assert statuses[:10] == [200] * 10
    assert statuses[10:] == [429, 429]


def test_distinct_real_clients_are_limited_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, CONCORDIA_TRUST_PROXY_HEADERS="1")
    for index in range(12):
        response = client.post(
            "/experiments", json={"title": "x"}, headers={"X-Forwarded-For": f"198.51.100.{index}"}
        )
        assert response.status_code == 200


def test_experiment_node_count_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experiment_service, "MAX_NODES_PER_EXPERIMENT", 3)
    client = _client(tmp_path, monkeypatch)
    experiment_id, auth = _new_experiment(client)
    codes = [
        client.post(f"/experiments/{experiment_id}/nodes", json=DNA_ROOT, headers=auth).status_code
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 409]


def test_security_headers_present_and_docs_exempt_from_csp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    api = client.get("/api/workspace")
    policy = api.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'self' https://huggingface.co" in policy
    assert api.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in client.get("/docs").headers
    secure = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert "max-age" in secure.headers["strict-transport-security"]


def test_unreachable_database_url_falls_back_to_sqlite() -> None:
    from concordia.api.workspace import _reachable_database_url

    assert _reachable_database_url(None) is None
    assert _reachable_database_url("not a dsn") is None
    assert _reachable_database_url("postgresql://u:p@127.0.0.1:1/db") is None


def test_oversized_and_unsized_bodies_are_rejected_before_parsing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    big = client.post(
        "/experiments",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "5000000"},
    )
    assert big.status_code == 413
    assert "Content-Security-Policy" in big.headers

    def chunks():
        yield b'{"title": "x"}'

    unsized = client.post(
        "/experiments", content=chunks(), headers={"content-type": "application/json"}
    )
    assert unsized.status_code == 411
    assert client.post("/experiments", json={"title": "ok"}).status_code == 200


def test_structure_claim_verification_is_open_and_spends_nothing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    plausible = {"clash_count": 0, "variable_domain_fraction": 1.0, "buried_surface_area": 1700}
    body = {
        "complex_id": "test-only",
        "receptor_chains": ["H", "L"],
        "ligand_chains": ["A"],
        "model": "mit/boltz2",
        "settings": {"sampling_steps": 50, "diffusion_samples": 5},
        "measurements": plausible,
    }

    # Plausible geometry alone cannot carry a claim: it rejected one of seven wrong poses.
    alone = client.post("/v1/structure-claims/verify", json=body)
    assert alone.status_code == 200
    assert alone.json()["status"] == "MISSING_EVIDENCE"
    assert alone.json()["rule_pack"] == "structure-rules-v1"

    # An independent model plus a counterfactual that moved the interface is enough.
    supported = client.post(
        "/v1/structure-claims/verify",
        json={
            **body,
            "measurements": {
                **plausible,
                "second_model_interface_agreement": 0.7,
                "perturbed_paratope_interface_agreement": 0.0,
            },
        },
    )
    assert supported.json()["status"] == "SUPPORTED"

    # Samples of one model are deliberately too weak to stand in for a second model.
    samples_only = client.post(
        "/v1/structure-claims/verify",
        json={
            **body,
            "measurements": {
                **plausible,
                "sample_interface_agreement": 0.95,
                "perturbed_paratope_interface_agreement": 0.0,
            },
        },
    )
    assert samples_only.json()["status"] == "PARTIALLY_SUPPORTED"
    assert any("independent" in reason for reason in samples_only.json()["reasons"])

    # Clashes contradict a pose outright, and the finding says why.
    clashing = client.post(
        "/v1/structure-claims/verify",
        json={**body, "measurements": {**plausible, "clash_count": 16}},
    )
    assert clashing.json()["status"] == "CONTRADICTED"
    assert "16 interface clashes" in clashing.json()["physical_findings"]


def test_structure_claim_verification_rejects_overlapping_chains(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/v1/structure-claims/verify",
        json={
            "complex_id": "test-only",
            "receptor_chains": ["H"],
            "ligand_chains": ["H"],
            "model": "mit/boltz2",
            "measurements": {"clash_count": 0},
        },
    )
    assert response.status_code == 422
    assert "disjoint" in response.json()["detail"]
