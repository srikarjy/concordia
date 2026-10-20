from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from concordia.api.reviews import review_router
from concordia.review.workflow import ReviewInput, ReviewStore, export_bundle, initial_review


def local_client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(review_router(tmp_path / "reviews"))
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_review_routes_refuse_non_local_clients(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(review_router(tmp_path / "reviews"))

    assert TestClient(app).get("/api/reviews").status_code == 403
    remote = TestClient(app, base_url="http://127.0.0.1", client=("203.0.113.5", 1))
    assert remote.get("/api/reviews").status_code == 403


def test_review_routes_refuse_cross_origin_requests(tmp_path: Path) -> None:
    client = local_client(tmp_path)
    response = client.get("/api/reviews", headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_example_review_round_trip_exports_a_verifiable_bundle(tmp_path: Path) -> None:
    client = local_client(tmp_path)
    example = client.get("/api/reviews/example").json()

    created = client.post("/api/reviews", json=example["input"])
    assert created.status_code == 200, created.text
    review_id = created.json()["review"]["review_id"]

    decided = client.post(
        f"/api/reviews/{review_id}/decisions",
        json={
            "expected_revision": 1,
            "candidate_id": "A13Q",
            "decision": "selected",
            "reason": "Both recorded sources agree on direction.",
        },
    )
    assert decided.status_code == 200, decided.text

    stale = client.post(
        f"/api/reviews/{review_id}/decisions",
        json={
            "expected_revision": 1,
            "candidate_id": "K6Q",
            "decision": "excluded",
            "reason": "stale tab",
        },
    )
    assert stale.status_code == 409

    assayed = client.post(
        f"/api/reviews/{review_id}/evidence",
        json={**example["assay"], "expected_revision": 2},
    )
    assert assayed.status_code == 200, assayed.text
    assert assayed.json()["review"]["assays"][0]["decisions_at_import"]["A13Q"] == "selected"

    for kind in ("html", "selected", "decisions"):
        assert client.get(f"/api/reviews/{review_id}/export/{kind}").status_code == 200

    bundle = client.get(f"/api/reviews/{review_id}/export/zip")
    assert bundle.status_code == 200
    extracted = tmp_path / "bundle"
    zipfile.ZipFile(io.BytesIO(bundle.content)).extractall(extracted)

    verified = subprocess.run(
        [sys.executable, "-I", "verify.py"], cwd=extracted, capture_output=True, text=True
    )
    assert verified.returncode == 0, verified.stderr
    assert "verified" in verified.stdout

    tampered = extracted / "inputs/001-candidates.csv"
    tampered.write_bytes(tampered.read_bytes().replace(b"K6Q", b"K6R", 1))
    rejected = subprocess.run(
        [sys.executable, "-I", "verify.py"], cwd=extracted, capture_output=True, text=True
    )
    assert rejected.returncode != 0
    assert "Input hash mismatch" in rejected.stderr


def test_bundle_verifies_attached_diagnostic_bytes(tmp_path: Path) -> None:
    example = local_client(tmp_path).get("/api/reviews/example").json()
    store = ReviewStore(tmp_path / "diagnostic-reviews")
    review = store.save(initial_review(ReviewInput(**example["input"])), 0, "Created")
    payload = export_bundle(
        review,
        [review],
        diagnostic_artifacts={"run.json": b'{"status":"unavailable"}\n'},
    )
    extracted = tmp_path / "diagnostic-bundle"
    zipfile.ZipFile(io.BytesIO(payload)).extractall(extracted)
    verified = subprocess.run(
        [sys.executable, "-I", "verify.py"], cwd=extracted, capture_output=True, text=True
    )
    assert verified.returncode == 0, verified.stderr
    diagnostic = extracted / "diagnostics/run.json"
    diagnostic.write_text('{"status":"altered"}\n', encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, "-I", "verify.py"], cwd=extracted, capture_output=True, text=True
    )
    assert rejected.returncode != 0
    assert "Diagnostic hash mismatch" in rejected.stderr
