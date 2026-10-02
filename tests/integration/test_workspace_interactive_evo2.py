"""Integration coverage for the interactive (non-tool) Evo2 endpoints on the
public workspace app — the surface actually served to visitors, as opposed to
the gateway/runner/queue unit tests that exercise each layer in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concordia.api.workspace import create_workspace_app


def test_generate_endpoint_fails_closed_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.post("/nvidia/evo2/generate", json={"sequence": "ACGT", "num_tokens": 4})

    assert response.status_code == 503
    assert "NVIDIA_API_KEY" in response.json()["detail"]


def test_generate_endpoint_rejects_invalid_bases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "irrelevant-since-validation-runs-first")
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.post("/nvidia/evo2/generate", json={"sequence": "ACGTXYZ"})

    assert response.status_code == 422


def test_generate_endpoint_is_excluded_from_the_read_only_tool_manifest(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    schema = client.get("/api/tools/openapi.json").json()

    assert "/nvidia/evo2/generate" not in schema["paths"]
    assert "/nvidia/evo2/forward" not in schema["paths"]


def test_forward_endpoint_fails_closed_without_configured_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", raising=False)
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    submit = client.post("/nvidia/evo2/forward", json={"sequence": "ACGT" * 2048})
    poll = client.get("/nvidia/evo2/forward/does-not-exist")

    assert submit.status_code == 503
    assert poll.status_code == 503


def test_forward_endpoint_rejects_wrong_length_before_queueing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", "http://127.0.0.1:1")
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.post("/nvidia/evo2/forward", json={"sequence": "ACGT" * 100})

    assert response.status_code == 422


def test_forward_endpoint_records_connection_failure_as_a_failed_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Port 1 is a reserved, never-listening port: the worker call fails fast
    # with a real connection error, exercising the actual failure path without
    # requiring a live ZeroGPU Space.
    monkeypatch.setenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", "http://127.0.0.1:1")
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    submit = client.post("/nvidia/evo2/forward", json={"sequence": "ACGT" * 2048})
    assert submit.status_code == 200
    job_id = submit.json()["job_id"]

    poll = client.get(f"/nvidia/evo2/forward/{job_id}")
    body = poll.json()
    assert poll.status_code == 200
    assert body["status"] == "FAILED"
    assert body["result"] is None
    assert body["error"]


def test_forward_poll_of_unknown_job_is_404_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", "http://127.0.0.1:1")
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.get("/nvidia/evo2/forward/does-not-exist")

    assert response.status_code == 404


def test_rate_limiting_ignores_forwarded_header_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without CONCORDIA_TRUST_PROXY_HEADERS, a spoofed X-Forwarded-For must not
    let a direct caller evade its own rate limit by claiming a new identity
    on every request.
    """

    monkeypatch.setenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("CONCORDIA_TRUST_PROXY_HEADERS", raising=False)
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    for index in range(2):
        response = client.post(
            "/nvidia/evo2/forward",
            json={"sequence": "ACGT" * 2048},
            headers={"X-Forwarded-For": f"10.0.0.{index}"},
        )
        assert response.status_code == 200

    third = client.post(
        "/nvidia/evo2/forward",
        json={"sequence": "ACGT" * 2048},
        headers={"X-Forwarded-For": "10.0.0.99"},
    )
    assert third.status_code == 429


def test_rate_limiting_trusts_forwarded_header_when_opted_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CONCORDIA_TRUST_PROXY_HEADERS", "1")
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    for _ in range(2):
        response = client.post(
            "/nvidia/evo2/forward",
            json={"sequence": "ACGT" * 2048},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert response.status_code == 200
    limited = client.post(
        "/nvidia/evo2/forward",
        json={"sequence": "ACGT" * 2048},
        headers={"X-Forwarded-For": "203.0.113.5"},
    )
    assert limited.status_code == 429

    # A different forwarded client is unaffected.
    other = client.post(
        "/nvidia/evo2/forward",
        json={"sequence": "ACGT" * 2048},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert other.status_code == 200


def test_esmfold_endpoint_fails_closed_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.post("/nvidia/esmfold/predict", json={"sequence": "MKT"})

    assert response.status_code == 503
    assert "NVIDIA_API_KEY" in response.json()["detail"]


def test_esmfold_endpoint_rejects_non_amino_acid_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "irrelevant-since-validation-runs-first")
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.post("/nvidia/esmfold/predict", json={"sequence": "BJOUZ"})

    assert response.status_code == 422


def test_esmfold_endpoint_is_excluded_from_the_read_only_tool_manifest(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    schema = client.get("/api/tools/openapi.json").json()

    assert "/nvidia/esmfold/predict" not in schema["paths"]


def test_colony_run_executes_a_real_fresh_colony(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    first = client.post("/colony/run", json={"population_size": 2, "generations": 1})
    second = client.post("/colony/run", json={"population_size": 2, "generations": 1})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["live"] is True
    first_id = first.json()["colony"]["spec"]["colony_id"]
    second_id = second.json()["colony"]["spec"]["colony_id"]
    assert first_id != second_id


def test_colony_run_rejects_invalid_survivor_count(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    response = client.post(
        "/colony/run", json={"population_size": 2, "generations": 1, "survivor_count": 5}
    )

    assert response.status_code == 422


def test_colony_run_is_excluded_from_the_read_only_tool_manifest(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    schema = client.get("/api/tools/openapi.json").json()

    assert "/colony/run" not in schema["paths"]
