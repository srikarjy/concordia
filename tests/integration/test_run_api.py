from fastapi.testclient import TestClient

from concordia.api.app import create_app


def request_body() -> dict[str, object]:
    return {
        "idempotency_key": "api-fixture-1",
        "sequence": {
            "sequence_id": "fixture:api-sequence",
            "sequence": "ACGTTGCAACGT",
            "assembly": "GRCh38",
            "region": "chr1:0-12",
            "strand": "+",
        },
        "scan_position": 4,
    }


def test_run_event_artifact_and_replay_api(tmp_path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/runs", json=request_body(), headers={"X-Request-ID": "req-1"})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "req-1"
        created = response.json()
        run_id = created["spec"]["run_id"]
        assert created["current_status"] == "COMPLETED"

        assert client.get(f"/runs/{run_id}").json() == created
        events = client.get(f"/runs/{run_id}/events", params={"limit": 2}).json()
        assert len(events["items"]) == 2
        assert events["next_cursor"] == 2
        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        assert len(artifacts) == 5
        replay = client.post(f"/runs/{run_id}/replay").json()
        assert replay["run"] == created
        assert replay["event_count"] == created["last_sequence_number"]

        duplicate = client.post("/runs", json=request_body())
        assert duplicate.json()["spec"]["run_id"] == run_id


def test_structured_api_errors_and_openapi(tmp_path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        missing = client.get("/runs/absent")
        assert missing.status_code == 404
        assert missing.json()["code"] == "RUN_NOT_FOUND"
        assert missing.headers["X-Request-ID"]

        first = client.post("/runs", json=request_body())
        assert first.status_code == 200
        changed = request_body()
        changed["scan_position"] = 5
        conflict = client.post("/runs", json=changed)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

        paths = client.get("/openapi.json").json()["paths"]
        assert "/runs" in paths
        assert "/runs/{run_id}/events" in paths
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}
