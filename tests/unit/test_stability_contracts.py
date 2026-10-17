from pathlib import Path
from typing import cast

import numpy as np
import pytest

from concordia.stability.contracts import (
    DestabilizingDDG,
    anchor_wild_type,
    freeze_manifest,
    from_destabilizing,
    from_stability,
    validate_wild_type_anchor,
)
from concordia.stability.measured import (
    MeasuredCandidate,
    MeasuredStabilityEngine,
    refuse_unsupported_signal,
    render_recommendation,
)
from concordia.stability.nl_schema import (
    extraction_digits_in_non_position_fields,
    extraction_schema,
    render_numeric_recommendation,
    validate_extraction_response,
)
from concordia.stability.structure_aware import should_refold
from scripts.select_tsuboyama_domain import (
    canonical_variant_payload,
    filtered_variant_digest,
    parse_variant_row,
)


@pytest.mark.parametrize("raw,expected", [(2.5, -2.5), (-1.25, 1.25)])
def test_external_destabilizing_score_is_converted_at_boundary(raw: float, expected: float) -> None:
    assert from_destabilizing(DestabilizingDDG(raw)).kcal_per_mol == expected


def test_source_stability_score_is_wrapped_without_flipping() -> None:
    assert from_stability(2.5).kcal_per_mol == 2.5


@pytest.mark.parametrize(
    "rows",
    [
        [{"sequence": "AAAA", "ddg_kcal_higher_is_more_stable": 1.0}],
    ],
)
def test_wild_type_rejects_nonzero_rows(rows: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError, match="wild-type"):
        anchor_wild_type(rows, wild_type_sequence="AAAA")


def test_wild_type_rejects_duplicate_rows() -> None:
    rows = [{"sequence": "AAAA", "ddg_kcal_higher_is_more_stable": 0.0}] * 2
    with pytest.raises(ValueError, match="duplicate"):
        anchor_wild_type(rows, wild_type_sequence="AAAA")


def test_wild_type_is_explicitly_anchored() -> None:
    anchored = anchor_wild_type([], wild_type_sequence="AAAA")
    assert anchored[0]["ddg_kcal_higher_is_more_stable"] == 0.0
    validate_wild_type_anchor(anchored, wild_type_sequence="AAAA")


@pytest.mark.parametrize(
    "rows",
    [[], [{"sequence": "BBBB", "ddg_kcal_higher_is_more_stable": 0.0}]],
)
def test_validation_rejects_missing_wild_type_row(rows: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        validate_wild_type_anchor(rows, wild_type_sequence="AAAA")


def test_manifest_is_write_once(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {"kind": "stability", "sign_convention": "ddg_kcal_higher_is_more_stable"}
    freeze_manifest(payload, path)
    freeze_manifest(payload, path)
    with pytest.raises(FileExistsError):
        freeze_manifest({**payload, "seed": 2}, path)


def test_digest_rejects_nan() -> None:
    row = parse_variant_row(
        {"domain_id": "A", "position": "9", "variant_id": "v9", "score": np.float64(np.nan)}
    )
    with pytest.raises(ValueError, match="non-finite"):
        filtered_variant_digest([row], "A")


def test_digest_normalizes_numpy_scalars() -> None:
    numpy_row = parse_variant_row(
        {"domain_id": "A", "position": np.int64(9), "variant_id": "v9", "score": np.float64(1.25)}
    )
    python_row = parse_variant_row(
        {"domain_id": "A", "position": 9, "variant_id": "v9", "score": 1.25}
    )
    assert filtered_variant_digest([numpy_row], "A") == filtered_variant_digest([python_row], "A")


def test_digest_orders_positions_numerically() -> None:
    rows = [
        parse_variant_row({"domain_id": "A", "position": "10", "variant_id": "v10", "score": 1.0}),
        parse_variant_row({"domain_id": "A", "position": "9", "variant_id": "v9", "score": 2.0}),
    ]
    payload = canonical_variant_payload(rows, "A")
    payload_rows = cast(list[dict[str, object]], payload["rows"])
    assert [row["position"] for row in payload_rows] == [9, 10]
    assert filtered_variant_digest(rows, "A") == filtered_variant_digest(list(reversed(rows)), "A")


def test_digest_scope_includes_domain_id() -> None:
    row_a = parse_variant_row({"domain_id": "A", "position": "9", "variant_id": "v9", "score": 1.0})
    row_b = parse_variant_row({"domain_id": "B", "position": "9", "variant_id": "v9", "score": 1.0})
    assert filtered_variant_digest([row_a], "A") != filtered_variant_digest([row_b], "B")


@pytest.fixture(scope="module")
def measured_engine() -> MeasuredStabilityEngine:
    return MeasuredStabilityEngine()


def test_measured_engine_refuses_hard_protected_residue(
    measured_engine: MeasuredStabilityEngine,
) -> None:
    candidate = MeasuredCandidate("external-hard", 21, "A")
    result = measured_engine.evaluate_candidate(candidate)
    assert result["refusal"]["refused"] is True
    assert result["refusal"]["triggers"][0]["code"] == "HARD_PROTECTED_UNIPROT"
    assert result["refusal"]["triggers"][0]["accession"] == "P02633"


def test_measured_engine_refuses_multi_mutant(
    measured_engine: MeasuredStabilityEngine,
) -> None:
    result = measured_engine.evaluate_candidate(
        MeasuredCandidate("external-double", 9, "Q", mutation_count=2)
    )
    assert result["refusal"]["triggers"][0]["code"] == "T3_MULTI_MUTANT_SINGLE_MODEL"


def test_measured_engine_uses_cross_position_distance_calibration(
    measured_engine: MeasuredStabilityEngine,
) -> None:
    distant = measured_engine.evaluate_candidate(measured_engine.rows["1IGV.pdb_L52Y"])
    accepted = measured_engine.evaluate_candidate(measured_engine.rows["1IGV.pdb_A13Q"])
    assert measured_engine.t2_recalibration["holdout_not_used"] is True
    assert measured_engine.t2_recalibration["new_threshold"] > measured_engine.t2_recalibration[
        "old_threshold"
    ]
    assert distant["refusal"]["refused"] is False
    assert accepted["refusal"]["refused"] is False


def test_unseen_position_is_soft_flagged_not_refused(
    measured_engine: MeasuredStabilityEngine,
) -> None:
    result = measured_engine.evaluate_candidate(
        MeasuredCandidate("1IGV.pdb_A13Q", 6, "Q")
    )
    assert result["refusal"]["refused"] is False
    assert result["soft_flags"][0]["code"] == "T1_POSITION_UNSEEN"


def test_structure_confidence_signal_is_refused() -> None:
    result = refuse_unsupported_signal("pLDDT")
    assert result.triggers[0]["code"] == "UNSUPPORTED_STRUCTURE_SIGNAL"


def test_unfilled_recommendation_slot_raises() -> None:
    with pytest.raises(ValueError, match="unfilled slots"):
        render_recommendation("Predicted stability: {score}", {"score": None})


def test_extraction_schema_allows_only_position_digits() -> None:
    schema = extraction_schema()
    response = {
        "intent": "stability_prediction",
        "target": {"positions": [16], "mutations": [{"position": 16, "to_aa": "A"}]},
        "specificity": "targeted",
    }
    validate_extraction_response(response, schema, range(1, 75))
    assert extraction_digits_in_non_position_fields(response) is False


def test_extraction_schema_rejects_digits_outside_positions() -> None:
    schema = extraction_schema()
    response = {
        "intent": "stability_prediction2",
        "target": {"positions": [16], "mutations": []},
        "specificity": "targeted",
    }
    with pytest.raises(ValueError, match="invalid extraction enum"):
        validate_extraction_response(response, schema, range(1, 75))


def test_extraction_schema_rejects_out_of_range_position() -> None:
    schema = extraction_schema()
    response = {
        "intent": "stability_prediction",
        "target": {"positions": [75], "mutations": []},
        "specificity": "targeted",
    }
    with pytest.raises(ValueError, match="outside"):
        validate_extraction_response(response, schema, range(1, 75))


def test_extraction_schema_requires_nonempty_tool_registry_is_not_applicable() -> None:
    schema = extraction_schema()
    assert "target" in schema["properties"]


def test_single_substitution_does_not_invoke_refold() -> None:
    assert should_refold(structure_exists=True, mutation_count=1) is False
    assert should_refold(structure_exists=True, mutation_count=2) is True


def test_numeric_recommendation_requires_deterministic_slots() -> None:
    response = {"action": "score", "tool": "stability", "evidence": "measured"}
    with pytest.raises(ValueError, match="slots"):
        render_numeric_recommendation(response, score=None, sigma=0.5)
