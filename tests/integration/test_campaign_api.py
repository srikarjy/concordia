from pathlib import Path

from fastapi.testclient import TestClient

from concordia.api.workspace import create_workspace_app


def test_campaign_api_requires_scoped_token_and_preserves_round_lineage(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "research binder",
            "objective": "find soluble binders",
            "target_sequence": "MKT",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    campaign_id = body["campaign"]["campaign_id"]
    token = body["access_token"]
    headers = {"X-Concordia-Campaign-Token": token}

    assert client.get(f"/campaigns/{campaign_id}").status_code == 401
    round_response = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "assay-v1", "batch_size": 2},
        headers=headers,
    )
    assert round_response.status_code == 200, round_response.text
    round_id = round_response.json()["round_id"]
    active_campaign = client.post(
        f"/campaigns/{campaign_id}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert active_campaign.status_code == 200
    active_round = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert active_round.status_code == 200
    audit_events = client.get(f"/campaigns/{campaign_id}/audit-events", headers=headers)
    assert audit_events.status_code == 200
    assert {event["action"] for event in audit_events.json()} >= {
        "campaign.status.transitioned",
        "round.status.transitioned",
    }
    invalid_campaign_transition = client.post(
        f"/campaigns/{campaign_id}/status",
        json={"status": "draft"},
        headers=headers,
    )
    assert invalid_campaign_transition.status_code == 409
    invalid_measurement = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/measurements",
        json={
            "candidate_id": "not-created",
            "metric": "binding",
            "unit": "nM",
            "method": "BLI",
            "status": "measured",
        },
        headers=headers,
    )
    assert invalid_measurement.status_code == 422

    parent_response = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        json={"sequence": "ACDE", "source": "import"},
        headers=headers,
    )
    assert parent_response.status_code == 200, parent_response.text
    parent_id = parent_response.json()["candidate_id"]
    child_response = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        json={
            "sequence": "ACDF",
            "source": "mutation",
            "parent_ids": [parent_id],
        },
        headers=headers,
    )
    assert child_response.status_code == 200, child_response.text
    assert child_response.json()["parent_ids"] == [parent_id]
    listed_rounds = client.get(f"/campaigns/{campaign_id}/rounds", headers=headers)
    assert listed_rounds.status_code == 200
    assert [item["round_id"] for item in listed_rounds.json()] == [round_id]
    listed_candidates = client.get(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates", headers=headers
    )
    assert listed_candidates.status_code == 200
    listed_candidate_ids = {item["candidate_id"] for item in listed_candidates.json()}
    assert listed_candidate_ids == {parent_id, child_response.json()["candidate_id"]}
    selected = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/recommendations:select",
        json={
            "policy": "greedy",
            "batch_size": 1,
            "seed": 7,
            "candidates": [
                {"candidate_id": parent_id, "score": 0.1},
                {"candidate_id": child_response.json()["candidate_id"], "score": 0.9},
            ],
        },
        headers=headers,
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["candidate_ids"] == [child_response.json()["candidate_id"]]
    assert selected.json()["rationale"]["seed"] == 7
    replay = client.post(
        f"/campaigns/{campaign_id}/recommendations/{selected.json()['recommendation_id']}/replay",
        json={
            "batch_size": 1,
            "seed": 7,
            "candidates": [
                {"candidate_id": parent_id, "score": 0.1},
                {"candidate_id": child_response.json()["candidate_id"], "score": 0.9},
            ],
        },
        headers=headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["passed"] is True
    replay_mismatch = client.post(
        f"/campaigns/{campaign_id}/recommendations/{selected.json()['recommendation_id']}/replay",
        json={
            "batch_size": 1,
            "seed": 7,
            "candidates": [
                {"candidate_id": parent_id, "score": 0.1},
                {"candidate_id": child_response.json()["candidate_id"], "score": 0.8},
            ],
        },
        headers=headers,
    )
    assert replay_mismatch.status_code == 200
    assert replay_mismatch.json()["passed"] is False

    model_run = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/model-runs",
        json={
            "candidate_ids": [parent_id],
            "provider": "nvidia-boltz",
            "model": "boltz",
            "model_version": "2",
            "execution_mode": "nim_inference",
            "output_artifact_digests": ["sha256:structure"],
        },
        headers=headers,
    )
    assert model_run.status_code == 200, model_run.text
    assert model_run.json()["scientific_use_allowed"] is False
    rejected_provider = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/model-runs",
        json={
            "candidate_ids": [parent_id],
            "provider": "arbitrary-http-endpoint",
            "model": "unknown",
            "model_version": "1",
            "execution_mode": "remote",
        },
        headers=headers,
    )
    assert rejected_provider.status_code == 422
    job_response = client.post(
        f"/campaigns/{campaign_id}/model-jobs",
        json={"model_run_id": model_run.json()["model_run_id"]},
        headers=headers,
    )
    assert job_response.status_code == 200, job_response.text
    listed_jobs = client.get(f"/campaigns/{campaign_id}/model-jobs", headers=headers)
    assert listed_jobs.status_code == 200
    assert listed_jobs.json()[0]["job_id"] == job_response.json()["job_id"]
    job_id = job_response.json()["job_id"]
    cancelled = client.post(
        f"/campaigns/{campaign_id}/model-jobs/{job_id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


def test_measured_stability_is_reachable_through_model_job_route(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-stability",
            "title": "measured stability",
            "objective": "rank 1IGV variants",
            "target_sequence": "A" * 74,
        },
    ).json()
    campaign_id = created["campaign"]["campaign_id"]
    headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    round_id = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "stability-v1", "batch_size": 8},
        headers=headers,
    ).json()["round_id"]
    candidate = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        json={
            "sequence": "A" * 74,
            "source": "measured-stability",
            "construct_metadata": {"variant_id": "1IGV.pdb_A13Q"},
        },
        headers=headers,
    ).json()
    model_run = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/model-runs",
        json={
            "candidate_ids": [candidate["candidate_id"]],
            "provider": "concordia-measured-stability",
            "model": "esm2-ridge-ensemble",
            "model_version": "gate4",
            "execution_mode": "local_frozen_measured_stability",
            "parameters": {
                "typed_request": {
                    "domain": "1IGV",
                    "mutation_groups": [
                        [{"from": "A", "position": 13, "to_aa": "Q"}]
                    ],
                }
            },
        },
        headers=headers,
    )
    assert model_run.status_code == 200, model_run.text
    job = client.post(
        f"/campaigns/{campaign_id}/model-jobs",
        json={"model_run_id": model_run.json()["model_run_id"]},
        headers=headers,
    )
    assert job.status_code == 200, job.text
    executed = client.post(
        f"/campaigns/{campaign_id}/model-jobs/{job.json()['job_id']}/run",
        headers=headers,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "succeeded"


def test_campaign_assay_csv_import_is_atomic_and_scoped(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "assay import",
            "objective": "test ingestion",
            "target_sequence": "MKT",
        },
    ).json()
    headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    campaign_id = created["campaign"]["campaign_id"]
    round_response = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "assay-v1"},
        headers=headers,
    )
    round_id = round_response.json()["round_id"]
    candidate = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        json={"sequence": "ACDE", "source": "import"},
        headers=headers,
    ).json()
    csv_text = (
        "candidate_id,metric,value,unit,method,status,replicate\n"
        f"{candidate['candidate_id']},binding,,nM,BLI,failed_expression,1\n"
    )
    imported = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/assays:import",
        json={"csv_text": csv_text},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported_count"] == 1

    invalid = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/assays:import",
        json={"csv_text": csv_text.replace("failed_expression", "measured")},
        headers=headers,
    )
    assert invalid.status_code == 200
    assert invalid.json()["imported_count"] == 0
    assert invalid.json()["errors"]


def test_campaign_tokens_cannot_cross_organizations(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    first = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "first",
            "objective": "test",
            "target_sequence": "MKT",
        },
    ).json()
    second = client.post(
        "/campaigns",
        json={
            "organization_id": "org-b",
            "title": "second",
            "objective": "test",
            "target_sequence": "MKT",
        },
    ).json()
    response = client.get(
        f"/campaigns/{second['campaign']['campaign_id']}",
        headers={"X-Concordia-Campaign-Token": first["access_token"]},
    )
    assert response.status_code == 403


def test_scoped_campaign_grants_enforce_roles_and_revocation(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "rbac",
            "objective": "test scoped access",
            "target_sequence": "MKT",
        },
    ).json()
    campaign_id = created["campaign"]["campaign_id"]
    owner_headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    grant = client.post(
        f"/campaigns/{campaign_id}/access-grants",
        json={"principal_id": "viewer-1", "role": "viewer", "lifetime_seconds": 3600},
        headers=owner_headers,
    )
    assert grant.status_code == 200, grant.text
    viewer_headers = {"X-Concordia-Campaign-Token": grant.json()["access_token"]}
    assert client.get(f"/campaigns/{campaign_id}", headers=viewer_headers).status_code == 200
    denied_write = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "v1"},
        headers=viewer_headers,
    )
    assert denied_write.status_code == 403
    revoked = client.post(
        f"/campaigns/{campaign_id}/access-grants/{grant.json()['grant_id']}/revoke",
        headers=owner_headers,
    )
    assert revoked.status_code == 204
    assert client.get(f"/campaigns/{campaign_id}", headers=viewer_headers).status_code == 403


def test_injected_bionemo_runner_is_reached_only_through_model_job(tmp_path: Path) -> None:
    from concordia.campaigns.worker import ConnectorResult

    class Runner:
        def train(self, *, dataset_id, model, framework_version, parameters):
            assert dataset_id == "dataset-1"
            assert model == "esm2"
            assert framework_version == "bionemo-v1"
            return ConnectorResult(
                provider_request_id="bionemo-job-1",
                output_artifact_digests=("checkpoint-digest",),
            )

    client = TestClient(
        create_workspace_app(
            tmp_path,
            tmp_path / "no-frontend",
            bionemo_training_runner=Runner(),
        )
    )
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "bionemo",
            "objective": "train",
            "target_sequence": "MKT",
        },
    ).json()
    campaign_id = created["campaign"]["campaign_id"]
    headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    round_id = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "v1"},
        headers=headers,
    ).json()["round_id"]
    model_run = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/model-runs",
        json={
            "provider": "nvidia-bionemo-framework",
            "model": "esm2",
            "model_version": "1",
            "execution_mode": "private_training",
            "parameters": {"dataset_id": "dataset-1", "framework_version": "bionemo-v1"},
        },
        headers=headers,
    ).json()
    job = client.post(
        f"/campaigns/{campaign_id}/model-jobs",
        json={"model_run_id": model_run["model_run_id"]},
        headers=headers,
    ).json()
    executed = client.post(
        f"/campaigns/{campaign_id}/model-jobs/{job['job_id']}/run",
        headers=headers,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "succeeded"


def test_frozen_dataset_benchmark_runs_through_authenticated_campaign_api(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "benchmark",
            "objective": "retrospective test",
            "target_sequence": "MKT",
        },
    ).json()
    campaign_id = created["campaign"]["campaign_id"]
    headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    round_id = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "v1"},
        headers=headers,
    ).json()["round_id"]
    sequences = ("AAAA", "AAAT", "AATT", "ATTT", "TTTT", "GGGG")
    for index, sequence in enumerate(sequences):
        candidate = client.post(
            f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
            json={"sequence": sequence, "source": "retrospective"},
            headers=headers,
        ).json()
        measurement = client.post(
            f"/campaigns/{campaign_id}/rounds/{round_id}/measurements",
            json={
                "candidate_id": candidate["candidate_id"],
                "metric": "binding",
                "value": float(index),
                "unit": "a.u.",
                "method": "fixture-assay",
                "status": "measured",
            },
            headers=headers,
        )
        assert measurement.status_code == 200, measurement.text
    listed_measurements = client.get(
        f"/campaigns/{campaign_id}/rounds/{round_id}/measurements",
        headers=headers,
    )
    assert listed_measurements.status_code == 200
    assert len(listed_measurements.json()) == len(sequences)
    dataset = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/datasets",
        params={"transformation_policy": "measured_only"},
        headers=headers,
    ).json()
    benchmark = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/datasets/{dataset['dataset_id']}/benchmark",
        params={"metric": "binding", "seeds": [1, 2]},
        headers=headers,
    )
    assert benchmark.status_code == 200, benchmark.text
    assert len(benchmark.json()["runs"]) == 2
    assert benchmark.json()["prospective_claim_allowed"] is False
    assert len(benchmark.json()["benchmark_digest"]) == 64
    benchmark_artifact = benchmark.json()["benchmark_artifact"]
    assert benchmark_artifact["kind"] == "report"
    artifact = client.get(
        f"/campaigns/{campaign_id}/artifacts/{benchmark_artifact['digest']}",
        headers=headers,
    )
    assert artifact.status_code == 200, artifact.text
    artifact_payload = artifact.json()
    assert artifact_payload["benchmark_digest"] == benchmark.json()["benchmark_digest"]
    assert artifact.headers["etag"] == f'"{benchmark_artifact["digest"]}"'
    artifact_path = (
        tmp_path
        / "artifacts"
        / "sha256"
        / benchmark_artifact["digest"][:2]
        / benchmark_artifact["digest"]
    )
    artifact_path.write_bytes(b"tampered")
    tampered = client.get(
        f"/campaigns/{campaign_id}/artifacts/{benchmark_artifact['digest']}",
        headers=headers,
    )
    assert tampered.status_code == 409
    assert tampered.json()["detail"] == "artifact integrity check failed"
    benchmark_events = client.get(f"/campaigns/{campaign_id}/audit-events", headers=headers).json()
    assert any(event["action"] == "benchmark.completed" for event in benchmark_events)
    validation = client.get(
        f"/campaigns/{campaign_id}/rounds/{round_id}/validation",
        headers=headers,
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["passed"] is True
    assert validation.json()["scientific_use_allowed"] is False


def test_study_layer_freezes_and_blocks_without_admission_evidence(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "study layer",
            "objective": "admission gate",
            "target_sequence": "MKT",
        },
    ).json()
    campaign_id = created["campaign"]["campaign_id"]
    headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    round_id = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "v1"},
        headers=headers,
    ).json()["round_id"]
    candidate = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        json={"sequence": "ACDE", "source": "study"},
        headers=headers,
    ).json()
    client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/measurements",
        json={
            "candidate_id": candidate["candidate_id"],
            "metric": "binding",
            "value": 1.0,
            "unit": "nM",
            "method": "fixture",
            "status": "measured",
        },
        headers=headers,
    )
    dataset = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/datasets",
        params={"transformation_policy": "measured_only"},
        headers=headers,
    ).json()
    study = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/studies",
        json={
            "protocol_digest": "a" * 64,
            "dataset_digest": dataset["dataset_digest"],
            "selection_manifest_digest": "b" * 64,
            "model_pin": "baseline@1",
            "evidence_families": ["assay", "structure"],
            "preregistered_outcomes": ["binding"],
        },
        headers=headers,
    )
    assert study.status_code == 200, study.text
    study_id = study.json()["study_id"]
    frozen = client.post(f"/campaigns/{campaign_id}/studies/{study_id}/freeze", headers=headers)
    assert frozen.status_code == 200, frozen.text
    admission = client.post(f"/campaigns/{campaign_id}/studies/{study_id}/admit", headers=headers)
    assert admission.status_code == 200, admission.text
    assert admission.json()["passed"] is False
    assert admission.json()["study"]["status"] == "blocked"


def test_campaign_evidence_and_report_endpoints_fail_closed_and_redact_sequences(
    tmp_path: Path,
) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "report",
            "objective": "track evidence",
            "target_sequence": "MKT",
        },
    )
    body = created.json()
    campaign_id = body["campaign"]["campaign_id"]
    token = body["access_token"]
    headers = {"X-Concordia-Campaign-Token": token}
    round_response = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "assay-v1"},
        headers=headers,
    )
    round_id = round_response.json()["round_id"]
    candidate_response = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        json={"sequence": "ACDE", "source": "design"},
        headers=headers,
    )
    candidate_id = candidate_response.json()["candidate_id"]

    claim_response = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/evidence-claims",
        json={
            "subject_id": candidate_id,
            "claim_type": "binding",
            "statement": "Candidate is a computational binding hypothesis.",
        },
        headers=headers,
    )
    assert claim_response.status_code == 200, claim_response.text
    claim_id = claim_response.json()["claim_id"]
    unsupported = client.post(
        f"/campaigns/{campaign_id}/evidence-claims/{claim_id}/verify",
        json={"status": "supported", "verifier": "reviewer"},
        headers=headers,
    )
    assert unsupported.status_code == 409
    rejected = client.post(
        f"/campaigns/{campaign_id}/evidence-claims/{claim_id}/verify",
        json={"status": "rejected", "verifier": "reviewer"},
        headers=headers,
    )
    assert rejected.status_code == 200

    report = client.get(
        f"/campaigns/{campaign_id}/rounds/{round_id}/report",
        headers=headers,
    )
    assert report.status_code == 200, report.text
    report_body = report.json()
    assert report_body["format"] == "concordia-biorender-manifest-v1"
    verified_report = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/report:verify",
        json=report_body,
        headers=headers,
    )
    assert verified_report.status_code == 200, verified_report.text
    assert verified_report.json()["valid"] is True
    tampered_report = {**report_body, "scientific_use_allowed": True}
    rejected_report = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/report:verify",
        json=tampered_report,
        headers=headers,
    )
    assert rejected_report.status_code == 200
    assert rejected_report.json()["valid"] is False
    assert "ACDE" not in report.text
    assert "audit_events" in report_body["lineage"]
    assert report_body["lineage"]["candidates"][0]["candidate_id"] == candidate_id
    assert report_body["lineage"]["evidence_claims"][0]["verification_status"] == "rejected"


def test_binder_design_plan_is_persisted_with_staged_providers(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(tmp_path, tmp_path / "no-frontend"))
    created = client.post(
        "/campaigns",
        json={
            "organization_id": "org-a",
            "title": "design",
            "objective": "binder design",
            "target_sequence": "MKT",
        },
    ).json()
    campaign_id = created["campaign"]["campaign_id"]
    headers = {"X-Concordia-Campaign-Token": created["access_token"]}
    round_id = client.post(
        f"/campaigns/{campaign_id}/rounds",
        json={"protocol_version": "v1"},
        headers=headers,
    ).json()["round_id"]
    response = client.post(
        f"/campaigns/{campaign_id}/rounds/{round_id}/design-plans",
        json={
            "target_structure_digest": "a" * 64,
            "contigs": "A1-100/0 15-25",
            "hotspot_residues": ["A50"],
            "num_backbones": 2,
            "sequences_per_backbone": 2,
            "max_cofolds": 2,
            "budget_units": 4,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert [stage["provider"] for stage in response.json()["stages"]] == [
        "nvidia-rfdiffusion",
        "nvidia-proteinmpnn",
        "nvidia-boltz",
    ]
