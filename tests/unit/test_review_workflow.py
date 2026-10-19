from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from concordia.review.workflow import (
    ConflictError,
    DecisionInput,
    EvidenceInput,
    InputError,
    ReviewInput,
    ReviewStore,
    add_evidence,
    comparison_flags,
    csv_export,
    initial_review,
    set_decision,
)

EXAMPLE = json.loads(
    (Path(__file__).parents[2] / "data/examples/variant-review.json").read_text()
)
REFERENCE = EXAMPLE["input"]["reference_sequence"]


def review_input(**overrides: Any) -> ReviewInput:
    return ReviewInput(**{**EXAMPLE["input"], **overrides})


def decide(review: dict[str, Any], cid: str, decision: str, **extra: str) -> None:
    set_decision(
        review,
        DecisionInput(
            expected_revision=review.get("revision", 1),
            candidate_id=cid,
            decision=decision,  # type: ignore[arg-type]
            reason=extra.get("reason", "test rationale"),
            override_reason=extra.get("override_reason", ""),
        ),
    )


def test_example_review_builds_candidates_and_protected_hits() -> None:
    review = initial_review(review_input())

    by_id = {c["candidate_id"]: c for c in review["candidates"]}
    assert list(by_id) == ["A13Q", "K6Q", "L52Y", "Q21E", "double-13-6"]
    assert by_id["Q21E"]["protected_hits"] == [21]
    assert by_id["double-13-6"]["positions"] == [13, 6]
    assert by_id["A13Q"]["sequence"][12] == "Q"
    assert review["scientific_use_allowed"] is False


def test_example_flags_source_disagreement_and_missing_evidence() -> None:
    flags = comparison_flags(initial_review(review_input()))

    # ThermoMPNN and the one-hot baseline swap K6Q and L52Y; A13Q is last in both.
    disagree = {
        cid for cid, values in flags.items() if any("Source ordering differs" in f for f in values)
    }
    assert disagree == {"K6Q", "L52Y"}
    assert "No imported prediction" in flags["Q21E"]
    assert any(f.startswith("Protected position") for f in flags["Q21E"])
    assert any(f.startswith("Multi-mutant") for f in flags["double-13-6"])


@pytest.mark.parametrize(
    ("candidates", "message"),
    [
        ("candidate_id,mutations\nx,K13Q\n", "does not match the reference"),
        ("candidate_id,mutations\nx,A13Q\ny,A13Q\n", "duplicate mutant sequence"),
        ("candidate_id,mutations\nx,A13A\n", "unchanged residue"),
        ("candidate_id,mutations\nx,A999Q\n", "does not match the reference"),
        ("candidate_id,mutation\nx,A13Q\n", "CSV columns must be exactly"),
    ],
)
def test_candidate_validation_rejects_inconsistent_inputs(candidates: str, message: str) -> None:
    with pytest.raises(InputError) as error:
        initial_review(review_input(candidates_csv=candidates, predictions_csv=""))
    assert any(message in e for e in error.value.errors)


def test_metric_with_conflicting_units_is_rejected() -> None:
    predictions = (
        "candidate_id,source,metric,value,unit,direction\n"
        "A13Q,model-a,ddg,1.0,kcal/mol,higher\n"
        "K6Q,model-b,ddg,1.0,kJ/mol,higher\n"
    )
    with pytest.raises(InputError) as error:
        initial_review(review_input(predictions_csv=predictions))
    assert any("incompatible units/direction" in e for e in error.value.errors)


def test_protected_positions_require_rationale() -> None:
    with pytest.raises(InputError):
        initial_review(review_input(constraint_note=" "))


def test_selecting_protected_variant_requires_override() -> None:
    review = initial_review(review_input())
    with pytest.raises(InputError):
        decide(review, "Q21E", "selected")
    decide(review, "Q21E", "selected", override_reason="binding loss is acceptable here")
    assert review["candidates"][3]["decision"] == "selected"


def test_assay_import_freezes_decisions_made_before_outcomes() -> None:
    review = {**initial_review(review_input()), "revision": 1}
    decide(review, "A13Q", "selected")
    decide(review, "L52Y", "excluded")

    add_evidence(review, EvidenceInput(expected_revision=1, **EXAMPLE["assay"]))
    decide(review, "A13Q", "excluded", reason="changed after seeing outcomes")

    frozen = review["assays"][0]["decisions_at_import"]
    assert frozen["A13Q"] == "selected"
    assert frozen["L52Y"] == "excluded"
    assert review["candidates"][0]["decision"] == "excluded"


def test_same_evidence_file_cannot_be_imported_twice() -> None:
    review = {**initial_review(review_input()), "revision": 1}
    add_evidence(review, EvidenceInput(expected_revision=1, **EXAMPLE["assay"]))
    with pytest.raises(InputError):
        add_evidence(
            review,
            EvidenceInput(expected_revision=1, **{**EXAMPLE["assay"], "label": "another"}),
        )


def test_assay_requires_recorded_context() -> None:
    review = {**initial_review(review_input()), "revision": 1}
    with pytest.raises(InputError):
        add_evidence(
            review, EvidenceInput(expected_revision=1, **{**EXAMPLE["assay"], "context": ""})
        )


def test_store_chains_revisions_and_rejects_stale_writes(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path)
    first = store.save(initial_review(review_input()), 0, "created")
    second = store.save(first, 1, "edited")

    assert second["previous_digest"] == first["artifact_digest"]
    assert store.load(first["review_id"], 1)["artifact_digest"] == first["artifact_digest"]
    with pytest.raises(ConflictError):
        store.save(first, 1, "stale tab")


def test_csv_export_neutralizes_spreadsheet_formulas() -> None:
    review = {**initial_review(review_input()), "revision": 1}
    decide(review, "A13Q", "selected", reason="=HYPERLINK(\"http://example.invalid\")")

    exported = csv_export(review, selected_only=True)
    assert "'=HYPERLINK" in exported
    assert "K6Q" not in exported
