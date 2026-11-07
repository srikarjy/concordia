from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from concordia.api.stability import stability_router


def test_local_scoring_preserves_candidates_refusals_and_ledger(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(stability_router(tmp_path))
    client = TestClient(app)
    response = client.post(
        "/api/stability/score",
        json={
            "domain": "1IGV",
            "mutations": ["A13Q", "K6Q", "L52Y", "Q21E", "A13Q:K6Q"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert len(report["candidates"]) == 3
    assert {item["variant_id"] for item in report["refusals"]} == {
        "1IGV.pdb_Q21E",
        "1IGV.pdb_A13Q:K6Q",
    }
    assert report["ledger_intact"] is True
    assert (
        client.post(
            "/api/stability/score",
            json={
                "domain": "other",
                "mutations": ["A13Q"],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/stability/score",
            json={
                "mutations": [],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/stability/score",
            json={
                "mutations": ["A999Q"],
            },
        ).status_code
        == 422
    )
