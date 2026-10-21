#!/usr/bin/env python3
"""Replay the committed Evo2 generation report into a local evidence ledger."""

# no network: reads committed report only.

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, time
from pathlib import Path

from concordia.events.sqlite import SQLiteEventLedger
from concordia.evidence.contracts import ModelRunEvidence

REPORT = Path("reports/nvidia-evo2-hosted-smoke.json")


def replay(state_root: Path) -> ModelRunEvidence:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    input_data = report.get("input", {})
    sequence = input_data.get("sequence")
    reasons = [
        "generation-only historical artifact; no forward scoring or biological "
        "validation in this record"
    ]
    if not report.get("model_version"):
        reasons.append(
            "model_version derived from report filename; source report has no model_version field"
        )
    settings = report.get("settings", report.get("params"))
    if settings is None:
        reasons.append(
            "settings/params block not recorded in source artifact: "
            f"{REPORT.as_posix()}"
        )
    if not sequence:
        reasons.append("input sequence not recorded in source artifact")
    if not report.get("response_artifact_digest"):
        reasons.append("response digest not recorded in source artifact")
    generated = report.get("validation", {}).get("generated_sequence")
    if not generated:
        reasons.append("generated sequence not recorded in source artifact")

    report_id = report.get("report_id") or REPORT.stem
    run_id = f"evo2-report-replay-{uuid.uuid4().hex}"
    input_hash = report.get("input_hash")
    if not input_hash:
        input_hash = hashlib.sha256(sequence.encode("utf-8")).hexdigest()
    params_hash = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest() if settings is not None else None
    raw_output_ref = report.get("response_artifact_digest") or generated
    evidence = ModelRunEvidence(
        run_id=run_id,
        model_id=report.get("model_id") or "unknown-evo2-model",
        model_version=report.get("model_version") or REPORT.stem,
        endpoint=report.get("endpoint"),
        input_hash=input_hash,
        params_hash=params_hash,
        raw_output_ref=raw_output_ref or f"report:{REPORT.as_posix()}",
        verification_status="unverifiable",
        verification_reasons=tuple(reasons),
        created_at=datetime.combine(
            date.fromisoformat(report["recorded_at"]), time.min, tzinfo=UTC
        ),
    )

    ledger = SQLiteEventLedger(state_root / "events.sqlite3")
    ledger.create_run(
        run_id=run_id,
        idempotency_key=run_id,
        command_digest=hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        payload={"report": REPORT.as_posix(), "report_id": report_id},
        event_id=f"{run_id}:created",
    )
    ledger.append(
        run_id,
        "MODEL_RUN_EVIDENCE",
        evidence.model_dump(mode="json"),
        expected_sequence=1,
        event_id=f"{run_id}:model-run-evidence",
    )
    print(json.dumps(evidence.model_dump(mode="json"), sort_keys=True))
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, default=Path(".concordia/evo2-replay-scratch"))
    args = parser.parse_args()
    replay(args.state_root)


if __name__ == "__main__":
    main()
