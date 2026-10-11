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


def test_experiment_node_count_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
