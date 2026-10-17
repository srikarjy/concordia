from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concordia.api.workspace import create_workspace_app


def test_capabilities_report_configuration_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", raising=False)
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    assert client.get("/api/capabilities").json() == {
        "nvidia": False, "forward": False, "attribution": False,
    }
    monkeypatch.setenv("NVIDIA_API_KEY", "test-secret-do-not-expose")
    monkeypatch.setenv("CONCORDIA_EVO2_FORWARD_SPACE_URL", "https://example.hf.space")
    configured = TestClient(create_workspace_app(tmp_path / "configured", "frontend/dist"))
    response = configured.get("/api/capabilities")
    assert response.json() == {"nvidia": True, "forward": True, "attribution": True}
    assert "test-secret" not in response.text


def test_connector_health_uses_state_shape_without_internal_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    payload = client.get("/api/connectors/health").json()
    for connector in payload["connectors"].values():
        assert set(connector) >= {"configured", "state", "reachable_at", "last_success"}
        assert connector["state"] in {
            "healthy", "rate_limited", "unavailable", "unconfigured", "untested"
        }
        assert "endpoint" not in connector
        assert "model" not in connector


def test_saved_workspace_api_exposes_only_fixture_artifacts(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    workspace = client.get("/api/workspace")
    assert workspace.status_code == 200
    payload = workspace.json()
    assert payload["scientific_use_allowed"] is False
    assert payload["execution_mode"] == "deterministic_colony_fixture"
    assert client.get("/api/graph").json()["nodes"]
    assert client.get("/api/events").json()["items"]
    assert client.get("/api/artifacts").json()
    assert client.get("/api/report").headers["content-type"].startswith("text/markdown")


def test_workspace_graph_focus_and_event_cursor_are_bounded(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    graph = client.get("/api/graph").json()
    focus = graph["nodes"][0]["id"]
    focused = client.get(f"/api/graph?focus={focus}&depth=0")
    assert focused.status_code == 200
    assert len(focused.json()["nodes"]) == 1
    assert client.get("/api/graph?depth=9").status_code == 422
    page = client.get("/api/events?cursor=0&limit=2").json()
    assert len(page["items"]) == 2
    assert page["next_cursor"] == 2


def test_workspace_publishes_only_read_only_evidence_tools(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))

    manifest = client.get("/.well-known/concordia-tools.json").json()
    schema = client.get(manifest["openapi_url"]).json()

    assert manifest["execution_exposed"] is False
    assert manifest["accepts_user_sequences"] is False
    assert manifest["model_inference_exposed"] is False
    assert manifest["scientific_use_allowed"] is False
    assert manifest["privacy_policy_url"].endswith("/privacy")
    assert set(manifest["operation_ids"]) == {
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
    }
    assert all(set(path_item) == {"get"} for path_item in schema["paths"].values())
    assert not any(path.startswith("/runs") for path in schema["paths"])
    assert "/api/stream" not in schema["paths"]
    assert schema["externalDocs"]["url"] == manifest["privacy_policy_url"]

    privacy = client.get("/privacy")
    assert privacy.status_code == 200
    assert privacy.headers["content-type"].startswith("text/markdown")
    assert "does not provide accounts" in privacy.text


def test_workspace_adds_public_security_headers(tmp_path: Path) -> None:
    response = TestClient(create_workspace_app(tmp_path, "frontend/dist")).get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
