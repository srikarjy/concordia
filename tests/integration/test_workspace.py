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
