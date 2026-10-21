from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from concordia.events.sqlite import SQLiteEventLedger
from concordia.evidence.contracts import ModelRunEvidence
from concordia.stability.measured import MeasuredStabilityEngine
from concordia.stability.request import TypedStabilityRequest, run_typed_request


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
    "overrides",
    [
        {"params_hash": None, "verification_status": "supported", "verification_reasons": ("gap",)},
        {"params_hash": None, "verification_status": "unverifiable", "verification_reasons": ()},
        {"params_hash": "not-a-hash"},
    ],
    ids=("missing-params-supported", "missing-params-no-reason", "malformed-params-hash"),
)
def test_invalid_evidence_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="1 validation error for ModelRunEvidence"):
        ModelRunEvidence.model_validate(_record(**overrides))
