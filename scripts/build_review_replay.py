"""Build the static, read-only replay of the 1IGV example variant review.

The replay is produced by the real review workflow: validated inputs, recorded
decisions, then published outcomes imported afterwards. Decisions are
illustrative and written by the project author, not by an external researcher.
Run: PYTHONPATH=src .venv/bin/python scripts/build_review_replay.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
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
AUTHOR_NOTE = (
    "Illustrative decisions written by the Concordia author to demonstrate the workflow. "
    "They are not an external researcher's review, a prospective experiment, or advice."
)
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
        store = ReviewStore(Path(state))
        review = store.save(initial_review(ReviewInput(**example["input"])), 0, "Created")
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
        (OUTPUT / "review.json").write_text(
            json.dumps({"author_note": AUTHOR_NOTE, "revisions": revisions}, indent=1)
        )
        (OUTPUT / "report.html").write_text(html_report(review))
        (OUTPUT / "selected.csv").write_text(csv_export(review, selected_only=True))
        (OUTPUT / "decisions.csv").write_text(csv_export(review))
        (OUTPUT / "bundle.zip").write_bytes(export_bundle(review, snapshots))
    print(f"replay written to {OUTPUT.relative_to(ROOT)} (revision {review['revision']})")


if __name__ == "__main__":
    main()
