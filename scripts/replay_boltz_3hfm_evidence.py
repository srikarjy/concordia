#!/usr/bin/env python3
"""Replay the committed 3HFM report into a local evidence ledger."""

# no network: this script reads a committed report only.

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, time
from pathlib import Path

from concordia.events.sqlite import SQLiteEventLedger
from concordia.evidence.contracts import ModelRunEvidence

REPORT = Path("reports/boltz2-3hfm-reference-reproduction.json")
MISSING_PARAMS_REASON = (
    "settings/params block not recorded in source artifact: "
    "reports/boltz2-3hfm-reference-reproduction.json"
)


def replay(state_root: Path) -> ModelRunEvidence:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    prediction = report["prediction"]
    run_id = f"boltz-report-replay-{uuid.uuid4().hex}"
    created_at = datetime.combine(date.fromisoformat(report["date"]), time.min, tzinfo=UTC)
    evidence = ModelRunEvidence(
        run_id=run_id,
        model_id=prediction["model_id"],
        model_version=report["report_id"],
        endpoint=prediction["endpoint"],
        input_hash=prediction["input_payload_hash"],
        params_hash=None,
        raw_output_ref=prediction["response_artifact_digest"],
        verification_status="unverifiable",
        verification_reasons=(MISSING_PARAMS_REASON,),
        created_at=created_at,
    )
    ledger = SQLiteEventLedger(state_root / "events.sqlite3")
    input_digest = hashlib.sha256(REPORT.read_bytes()).hexdigest()
    ledger.create_run(
        run_id=run_id,
        idempotency_key=run_id,
        command_digest=input_digest,
        payload={"report_id": report["report_id"]},
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
    parser.add_argument("--state-root", type=Path, default=Path(".concordia/boltz-replay-scratch"))
    args = parser.parse_args()
    replay(args.state_root)


if __name__ == "__main__":
    main()
