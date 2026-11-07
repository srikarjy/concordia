from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from concordia.events.sqlite import SQLiteEventLedger
from concordia.evidence.contracts import ModelRunEvidence
from concordia.review.workflow import ReviewInput, ReviewStore, export_bundle, initial_review
from concordia.stability.measured import MeasuredStabilityEngine
from concordia.stability.request import TypedStabilityRequest, run_typed_request
from scripts.verify_review_replay import validate_bundle_archive


@pytest.fixture(scope="module")
def igv_records(tmp_path_factory: pytest.TempPathFactory) -> tuple[ModelRunEvidence, ...]:
    root = tmp_path_factory.mktemp("igv-evidence")
    report = run_typed_request(
        TypedStabilityRequest.from_cli("1IGV", "A13Q,K6Q,L52Y"),
        state_root=root,
        engine=MeasuredStabilityEngine(),
    )
    events = SQLiteEventLedger(root / "events.sqlite3").events(report["run_id"]).items
    return tuple(
        ModelRunEvidence.model_validate(event.payload)
        for event in events
        if event.event_type == "MODEL_RUN_EVIDENCE"
    )


@pytest.fixture(scope="module")
def boltz_records(tmp_path_factory: pytest.TempPathFactory) -> tuple[ModelRunEvidence, ...]:
    root = Path(__file__).resolve().parents[2]
    state = tmp_path_factory.mktemp("boltz-evidence")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    result = subprocess.run(
        [sys.executable, "scripts/replay_boltz_3hfm_evidence.py", "--state-root", str(state)],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    run_id = json.loads(result.stdout)["run_id"]
    events = SQLiteEventLedger(state / "events.sqlite3").events(run_id).items
    return tuple(
        ModelRunEvidence.model_validate(event.payload)
        for event in events
        if event.event_type == "MODEL_RUN_EVIDENCE"
    )


def _replay_records(
    tmp_path_factory: pytest.TempPathFactory, script: str, prefix: str
) -> tuple[tuple[ModelRunEvidence, ...], bool]:
    root = Path(__file__).resolve().parents[2]
    state = tmp_path_factory.mktemp(prefix)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    result = subprocess.run(
        [sys.executable, f"scripts/{script}", "--state-root", str(state)],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    run_id = payload["run_id"]
    ledger = SQLiteEventLedger(state / "events.sqlite3")
    events = ledger.events(run_id).items
    records = tuple(
        ModelRunEvidence.model_validate(event.payload)
        for event in events
        if event.event_type == "MODEL_RUN_EVIDENCE"
    )
    return records, ledger.verify_chain(run_id).intact


@pytest.fixture(scope="module")
def evo2_records(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tuple[ModelRunEvidence, ...], bool]:
    return _replay_records(tmp_path_factory, "replay_evo2_generation_evidence.py", "evo2-evidence")


@pytest.fixture(scope="module")
def thermompnn_records(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tuple[ModelRunEvidence, ...], bool]:
    return _replay_records(
        tmp_path_factory, "replay_thermompnn_feasibility.py", "thermompnn-evidence"
    )


def test_igv_run_emits_valid_evidence(igv_records: tuple[ModelRunEvidence, ...]) -> None:
    assert len(igv_records) >= 1


def test_igv_params_hash_is_sha256(igv_records: tuple[ModelRunEvidence, ...]) -> None:
    value = igv_records[0].params_hash
    assert value is not None and len(value) == 64 and re.fullmatch(r"[0-9a-f]{64}", value)


def test_igv_verification_status_is_explicit(igv_records: tuple[ModelRunEvidence, ...]) -> None:
    assert igv_records[0].verification_status in {"supported", "unverifiable", "refused"}


def test_igv_model_identity_is_not_ridge(igv_records: tuple[ModelRunEvidence, ...]) -> None:
    assert igv_records[0].model_id and igv_records[0].model_id != "ridge-aa-composition"


def test_boltz_replay_emits_valid_evidence(boltz_records: tuple[ModelRunEvidence, ...]) -> None:
    assert len(boltz_records) >= 1


def test_boltz_params_are_not_recorded(boltz_records: tuple[ModelRunEvidence, ...]) -> None:
    assert boltz_records[0].params_hash is None


def test_boltz_is_unverifiable(boltz_records: tuple[ModelRunEvidence, ...]) -> None:
    assert boltz_records[0].verification_status == "unverifiable"


def test_boltz_reason_names_source_report(boltz_records: tuple[ModelRunEvidence, ...]) -> None:
    assert any(
        "reports/boltz2-3hfm-reference-reproduction.json" in reason
        for reason in boltz_records[0].verification_reasons
    )


def test_both_records_use_schema_version_one(
    igv_records: tuple[ModelRunEvidence, ...], boltz_records: tuple[ModelRunEvidence, ...]
) -> None:
    assert igv_records[0].schema_version == boltz_records[0].schema_version == 1


def test_evo2_replay_emits_valid_evidence_and_intact_ledger(
    evo2_records: tuple[tuple[ModelRunEvidence, ...], bool],
) -> None:
    records, intact = evo2_records
    assert records
    assert intact
    assert records[0].model_id == "arc/evo2-40b-generate"
    assert records[0].model_version == "nvidia-evo2-hosted-smoke"
    assert records[0].params_hash is None
    assert records[0].verification_status == "unverifiable"
    assert records[0].schema_version == 1
    assert any("no model_version field" in reason for reason in records[0].verification_reasons)


def test_thermompnn_replay_emits_valid_unverifiable_evidence_and_intact_ledger(
    thermompnn_records: tuple[tuple[ModelRunEvidence, ...], bool],
) -> None:
    records, intact = thermompnn_records
    assert records
    assert intact
    assert records[0].model_id == "thermompnn"
    assert records[0].params_hash is None
    assert records[0].verification_status == "unverifiable"
    assert any("checkpoint unavailable" in reason for reason in records[0].verification_reasons)
    assert records[0].created_at.isoformat() == "2026-10-20T00:00:00+00:00"
    assert records[0].schema_version == 1


def test_v2_review_bundle_round_trips_all_four_emitters(
    tmp_path: Path,
    igv_records: tuple[ModelRunEvidence, ...],
    boltz_records: tuple[ModelRunEvidence, ...],
    evo2_records: tuple[tuple[ModelRunEvidence, ...], bool],
    thermompnn_records: tuple[tuple[ModelRunEvidence, ...], bool],
) -> None:
    evidence = [
        igv_records[0],
        boltz_records[0],
        evo2_records[0][0],
        thermompnn_records[0][0],
    ]
    review = initial_review(
        ReviewInput(
            title="Emitter evidence integration",
            objective="Round-trip four recorded model evidence sources.",
            reference_sequence="ACDEFGHIKLMNPQRSTVWY",
            candidates_csv="candidate_id,mutations\nvariant-1,A1G\n",
            model_run_evidence=evidence,
        )
    )
    stored = ReviewStore(tmp_path / "review-store").save(review, 0, "Created")
    payload = export_bundle(stored, [stored])
    archive = zipfile.ZipFile(io.BytesIO(payload))
    bundle = json.loads(archive.read("bundle.json"))

    assert bundle["schema_version"] == 2
    assert len(bundle["model_run_evidence"]) == 4
    assert len(validate_bundle_archive(archive)) == 4
    extracted = tmp_path / "v2-bundle"
    archive.extractall(extracted)
    verified = subprocess.run(
        [sys.executable, "-I", "verify.py"], cwd=extracted, capture_output=True, text=True
    )
    assert verified.returncode == 0, verified.stderr


def test_v1_review_bundle_without_evidence_remains_accepted() -> None:
    root = Path(__file__).resolve().parents[2]
    with zipfile.ZipFile(root / "frontend/public/review-replay/r7-bundle.zip") as archive:
        assert "bundle.json" not in archive.namelist()
        assert validate_bundle_archive(archive) == ()


def _record(**overrides: object) -> dict[str, object]:
    return {
        "run_id": "test-run",
        "model_id": "test-model",
        "model_version": "1",
        "input_hash": "a" * 64,
        "params_hash": "b" * 64,
        "raw_output_ref": "sha256:test-output",
        "verification_status": "supported",
        "created_at": "2026-10-21T00:00:00Z",
        **overrides,
    }


@pytest.mark.parametrize(
    "overrides,match",
    [
        (
            {
                "params_hash": None,
                "verification_status": "supported",
                "verification_reasons": ("gap",),
            },
            "verification_status",
        ),
        (
            {
                "params_hash": None,
                "verification_status": "unverifiable",
                "verification_reasons": (),
            },
            "verification reason",
        ),
        ({"params_hash": "not-a-hash"}, "params_hash"),
    ],
    ids=("missing-params-supported", "missing-params-no-reason", "malformed-params-hash"),
)
def test_invalid_evidence_is_rejected(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        ModelRunEvidence.model_validate(_record(**overrides))
