from fastapi.testclient import TestClient

from concordia.api.app import create_app
from concordia.runtime.worker import LocalWorker


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
        assert created["current_status"] == "SCHEDULED"

        worker = LocalWorker.create(client.app.state.run_service, owner="api-test-worker")
        completed = worker.run_once(run_id=run_id)
        assert completed is not None
        assert completed.current_status == "COMPLETED"

        persisted = client.get(f"/runs/{run_id}").json()
        assert persisted["current_status"] == "COMPLETED"
        events = client.get(f"/runs/{run_id}/events", params={"limit": 2}).json()
        assert len(events["items"]) == 2
        assert events["next_cursor"] == 2
        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        assert len(artifacts) == 5
        replay = client.post(f"/runs/{run_id}/replay").json()
        assert replay["run"] == persisted
        assert replay["event_count"] == persisted["last_sequence_number"]

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
        assert "/runs/{run_id}/cancel" in paths
        assert "/runs/{run_id}/stream" in paths
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}


def test_cancel_and_sse_reconnection(tmp_path) -> None:
    app = create_app(tmp_path, sse_poll_seconds=0.001)
    with TestClient(app) as client:
        cancelled_response = client.post("/runs", json=request_body())
        cancelled_run_id = cancelled_response.json()["spec"]["run_id"]
        cancelled = client.post(f"/runs/{cancelled_run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["current_status"] == "CANCELLED"

        completed_body = request_body()
        completed_body["idempotency_key"] = "api-fixture-sse"
        scheduled = client.post("/runs", json=completed_body).json()
        run_id = scheduled["spec"]["run_id"]
        worker = LocalWorker.create(app.state.run_service, owner="sse-worker")
        completed = worker.run_once(run_id=run_id)
        assert completed is not None

        stream = client.get(
            f"/runs/{run_id}/stream", headers={"Last-Event-ID": "2"}
        )
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        event_ids = [
            int(line.removeprefix("id: "))
            for line in stream.text.splitlines()
            if line.startswith("id: ")
        ]
        assert event_ids
        assert min(event_ids) == 3
        assert max(event_ids) == completed.last_sequence_number

        invalid_cursor = client.get(
            f"/runs/{run_id}/stream", headers={"Last-Event-ID": "invalid"}
        )
        assert invalid_cursor.status_code == 400
        assert invalid_cursor.json()["code"] == "INVALID_REQUEST"
