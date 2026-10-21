#!/usr/bin/env python3
"""Replay the committed ThermoMPNN feasibility report into a local ledger."""

# no network: reads committed report only.

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import UTC, datetime, time
from pathlib import Path

from concordia.events.sqlite import SQLiteEventLedger
from concordia.evidence.contracts import ModelRunEvidence

REPORT = Path("reports/thermompnn-feasibility/2026-10-20-1igv-s1a.json")
CREATED_AT_SOURCE = "2026-10-20T00:00:00+00:00"


def replay(state_root: Path) -> ModelRunEvidence:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    variant_id = report["preflight"]["source_manifest"]["variant_id"]
    run_id = f"thermompnn-report-replay-{uuid.uuid4().hex}"
    evidence = ModelRunEvidence(
        run_id=run_id,
        model_id=report.get("model_id", "thermompnn"),
        model_version=report.get("model_version", REPORT.stem),
        endpoint=None,
        input_hash=hashlib.sha256(variant_id.encode("utf-8")).hexdigest(),
        params_hash=None,
        raw_output_ref=REPORT.as_posix(),
        verification_status="unverifiable",
        verification_reasons=(
            "execution not attempted; upstream checkpoint unavailable — see "
            "reports/thermompnn-feasibility/2026-10-20-1igv-s1a.json",
            "created_at derived from git commit date; source report has no created_at field",
        ),
        created_at=datetime.combine(
            datetime.fromisoformat(CREATED_AT_SOURCE).date(), time.min, tzinfo=UTC
        ),
    )
    ledger = SQLiteEventLedger(state_root / "events.sqlite3")
    ledger.create_run(
        run_id=run_id,
        idempotency_key=run_id,
        command_digest=hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        payload={"report": REPORT.as_posix(), "variant_id": variant_id},
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
    parser.add_argument(
        "--state-root", type=Path, default=Path(".concordia/thermompnn-replay-scratch")
    )
    args = parser.parse_args()
    replay(args.state_root)


if __name__ == "__main__":
    main()
