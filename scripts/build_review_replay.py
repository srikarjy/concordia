"""Build the static, read-only replay of the 1IGV example variant review.

The replay is produced by the real review workflow: validated inputs, recorded
decisions, then published outcomes imported afterwards. Decisions are
illustrative and written by the project author, not by an external researcher.
Run: PYTHONPATH=src .venv/bin/python scripts/build_review_replay.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from concordia.review.workflow import (
    DecisionInput,
    EvidenceInput,
    ReviewInput,
    ReviewStore,
    add_evidence,
    comparison_flags,
    csv_export,
    export_bundle,
    html_report,
    initial_review,
    set_decision,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "data/examples/variant-review.json"
OUTPUT = ROOT / "frontend/public/review-replay"
FEASIBILITY_RECORD = ROOT / "reports/thermompnn-feasibility/2026-10-20-1igv-s1a.json"
AUTHOR_NOTE = (
    "Illustrative decisions written by the Concordia author to demonstrate the workflow. "
    "They are not an external researcher's review, a prospective experiment, or advice."
)
STATIC_REVIEW_ID = "1igv-retrospective-example-v1"
STATIC_STARTED_AT = datetime(2026, 10, 20, 18, 27, 18, tzinfo=UTC)
STATIC_ZIP_TIMESTAMP = (2026, 10, 20, 18, 27, 18)
DECISIONS = [
    ("A13Q", "excluded", "Both recorded sources predict destabilization; last in both orderings."),
    (
        "K6Q",
        "selected",
        "Smallest predicted destabilization in ThermoMPNN; one-hot baseline orders it "
        "second, so the ordering flag stays visible.",
    ),
    (
        "L52Y",
        "deferred",
        "Sources disagree: ThermoMPNN predicts destabilization, the one-hot baseline is "
        "near neutral. Needs more evidence before selection.",
    ),
    ("Q21E", "excluded", "Touches protected binding-site position 21; no prediction supplied."),
    (
        "double-13-6",
        "excluded",
        "Multi-mutant containing A13Q; single-mutation predictions do not establish "
        "the combination effect.",
    ),
]


def main() -> None:
    example = json.loads(EXAMPLE.read_text())
    with tempfile.TemporaryDirectory() as state:
        save_count = 0

        def clock() -> datetime:
            nonlocal save_count
            value = STATIC_STARTED_AT + timedelta(seconds=save_count)
            save_count += 1
            return value

        store = ReviewStore(Path(state), clock=clock)
        review = store.save(
            initial_review(ReviewInput(**example["input"]), review_id=STATIC_REVIEW_ID),
            0,
            "Created",
        )
        for candidate_id, decision, reason in DECISIONS:
            set_decision(
                review,
                DecisionInput(
                    expected_revision=review["revision"],
                    candidate_id=candidate_id,
                    decision=decision,  # type: ignore[arg-type]
                    reason=reason,
                ),
            )
            review = store.save(
                review, review["revision"], f"Decision: {candidate_id} → {decision}"
            )
        body = EvidenceInput(expected_revision=review["revision"], **example["assay"])
        add_evidence(review, body)
        review = store.save(review, body.expected_revision, f"Imported assay: {body.label}")

        history = store.history(review["review_id"])
        snapshots = [store.load(review["review_id"], n) for n in range(1, review["revision"] + 1)]
        revisions = [
            {"review": snapshot, "flags": comparison_flags(snapshot), "history": history}
            for snapshot in snapshots
        ]

        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        OUTPUT.mkdir(parents=True)
        if not FEASIBILITY_RECORD.is_file():
            raise FileNotFoundError(f"missing bounded feasibility record: {FEASIBILITY_RECORD}")
        feasibility_bytes = FEASIBILITY_RECORD.read_bytes()
        digest_path = FEASIBILITY_RECORD.with_suffix(FEASIBILITY_RECORD.suffix + ".sha256")
        if hashlib.sha256(feasibility_bytes).hexdigest() != digest_path.read_text().strip():
            raise ValueError("ThermoMPNN feasibility record checksum does not match")
        (OUTPUT / "thermompnn-feasibility.json").write_bytes(feasibility_bytes)
        (OUTPUT / "thermompnn-feasibility.json.sha256").write_text(
            digest_path.read_text(), encoding="utf-8"
        )
        (OUTPUT / "review.json").write_text(
            json.dumps({"author_note": AUTHOR_NOTE, "revisions": revisions}, indent=1)
        )
        for snapshot in snapshots:
            prefix = f"r{snapshot['revision']}"
            history_to_revision = snapshots[: snapshot["revision"]]
            (OUTPUT / f"{prefix}-report.html").write_text(html_report(snapshot))
            (OUTPUT / f"{prefix}-selected.csv").write_text(csv_export(snapshot, selected_only=True))
            (OUTPUT / f"{prefix}-decisions.csv").write_text(csv_export(snapshot))
            (OUTPUT / f"{prefix}-bundle.zip").write_bytes(
                export_bundle(
                    snapshot,
                    history_to_revision,
                    diagnostic_artifacts={"thermompnn-feasibility.json": feasibility_bytes},
                    zip_timestamp=STATIC_ZIP_TIMESTAMP,
                )
            )
    print(f"replay written to {OUTPUT.relative_to(ROOT)} (revision {review['revision']})")


if __name__ == "__main__":
    main()
