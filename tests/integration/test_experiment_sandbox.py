from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from concordia.api.workspace import create_workspace_app


def test_experiment_api_builds_private_branching_dag(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    created = client.post(
        "/experiments",
        json={"title": "BRCA1 variant study", "description": "Interactive sandbox"},
    )
    assert created.status_code == 200
    experiment_id = created.json()["experiment"]["experiment_id"]
    token = created.json()["access_token"]
    headers = {"X-Concordia-Experiment-Token": token}

    root = client.post(
        f"/experiments/{experiment_id}/nodes",
        headers=headers,
        json={
            "kind": "dna_sequence",
            "operation": "root",
            "label": "Reference",
            "payload": {"payload_type": "dna", "sequence": "ACGT"},
        },
    )
    assert root.status_code == 200
    root_id = root.json()["node_id"]

    variant = client.post(
        f"/experiments/{experiment_id}/nodes",
        headers=headers,
        json={
            "kind": "dna_sequence",
            "operation": "mutate",
            "label": "Variant A",
            "branch": "variant-a",
            "parent_ids": [root_id],
            "payload": {"payload_type": "dna", "sequence": "ATGT"},
            "mutations": [{"position": 1, "reference": "C", "alternate": "T"}],
        },
    )
    assert variant.status_code == 200

    manifest = client.get(f"/experiments/{experiment_id}", headers=headers)
    assert manifest.status_code == 200
    assert len(manifest.json()["nodes"]) == 2
    assert manifest.json()["edges"] == [
        {"parent_id": root_id, "child_id": variant.json()["node_id"], "relation": "wasDerivedFrom"}
    ]
    assert len(manifest.json()["manifest_digest"]) == 64
    payload = client.get(
        f"/experiments/{experiment_id}/nodes/{root_id}/payload", headers=headers
    )
    assert payload.json()["sequence"] == "ACGT"


def test_experiment_api_enforces_capability_token(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    created = client.post("/experiments", json={"title": "Private experiment"}).json()
    experiment_id = created["experiment"]["experiment_id"]

    assert client.get(f"/experiments/{experiment_id}").status_code == 401
    assert client.get(
        f"/experiments/{experiment_id}",
        headers={"X-Concordia-Experiment-Token": "wrong"},
    ).status_code == 403


def test_experiment_endpoints_are_not_in_read_only_tool_contract(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    schema = client.get("/api/tools/openapi.json").json()

    assert not any(path.startswith("/experiments") for path in schema["paths"])


def test_experiment_evo2_operation_fails_before_lineage_without_api_key(
    tmp_path: Path,
) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    created = client.post("/experiments", json={"title": "Evo2 experiment"}).json()
    experiment_id = created["experiment"]["experiment_id"]
    headers = {"X-Concordia-Experiment-Token": created["access_token"]}
    root = client.post(
        f"/experiments/{experiment_id}/nodes",
        headers=headers,
        json={
            "kind": "dna_sequence",
            "operation": "root",
            "label": "Seed",
            "payload": {"payload_type": "dna", "sequence": "ACGT"},
        },
    ).json()

    response = client.post(
        f"/experiments/{experiment_id}/operations/evo2/generate",
        headers=headers,
        json={"parent_node_id": root["node_id"], "sequence": "ACGT", "num_tokens": 4},
    )

    assert response.status_code == 503
    manifest = client.get(f"/experiments/{experiment_id}", headers=headers).json()
    assert len(manifest["nodes"]) == 1
    assert manifest["edges"] == []


def test_experiment_model_operation_rejects_sequence_that_does_not_match_parent(
    tmp_path: Path,
) -> None:
    client = TestClient(create_workspace_app(tmp_path, "frontend/dist"))
    created = client.post("/experiments", json={"title": "Mismatch"}).json()
    experiment_id = created["experiment"]["experiment_id"]
    headers = {"X-Concordia-Experiment-Token": created["access_token"]}
    root = client.post(
        f"/experiments/{experiment_id}/nodes",
        headers=headers,
        json={
            "kind": "dna_sequence",
            "operation": "root",
            "label": "Seed",
            "payload": {"payload_type": "dna", "sequence": "ACGT"},
        },
    ).json()

    response = client.post(
        f"/experiments/{experiment_id}/operations/evo2/generate",
        headers=headers,
        json={"parent_node_id": root["node_id"], "sequence": "TGCA"},
    )

    assert response.status_code == 409
