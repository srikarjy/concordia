from pathlib import Path

from fastapi.testclient import TestClient

from concordia.api.workspace import create_workspace_app


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
