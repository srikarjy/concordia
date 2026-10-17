from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from concordia.genomics.evo2_attribution import (
    Evo2AttributionError,
    Evo2AttributionResult,
    ZeroGpuEvo2AttributionRunner,
)
from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore

CHECKPOINT = "arcinstitute/evo2_7b@bda0089f92582d5baabf0f22d9fc85f3588f6b58/evo2_7b.pt"
TARGET = "mean_next_base_log_likelihood"
WINDOW = 8_192


def scoring_semantics() -> Evo2ScoringSemantics:
    return Evo2ScoringSemantics(
        target=TARGET,
        tokenizer="CharLevelTokenizer-vocab-512",
        retained_score_artifacts=(
            "token_ids",
            "target_token_log_probabilities_float32",
            "sum_log_likelihood_float64",
            "mean_log_likelihood_float64",
        ),
    )


def sequence(length: int = WINDOW) -> GenomicSequence:
    return GenomicSequence(
        sequence_id="hbb:test-window", sequence="ACGT" * (length // 4), strand="+"
    )


def sse_body(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def completed_worker_record(**overrides: object) -> dict:
    """A worker record shaped like a real ``attribute_sequence`` return value.

    Every position gets the same estimates except position 7, which is made the
    single most damaging substitution so the ranking is checkable.
    """

    estimates = {base: [-0.5] * WINDOW for base in "ACGT"}
    estimates["G"][7] = -42.0
    record: dict = {
        "schema_version": 1,
        "model_checkpoint": CHECKPOINT,
        "target": TARGET,
        "attribution_method": "gradient_x_embedding_difference_first_order",
        "execution_status": "COMPLETED",
        "sequence_length": WINDOW,
        "reference_total_log_likelihood": -9162.54,
        "backward_seconds": 7.11,
        "peak_memory_bytes": 21_942_000_000,
        "gradient_finite": True,
        "substitution_estimates": estimates,
        "agreement_check": {
            "pairs": 24,
            "spearman_predicted_vs_exact": 0.499,
            "sign_agreement": 0.625,
            "top_quartile_recall": 0.5,
            "checked": [],
        },
        "scientific_use_allowed": False,
    }
    record.update(overrides)
    return record


def build_runner(record: object, tmp_path: Path, **kwargs: object):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/call/attribute_sequence"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        return httpx.Response(
            200,
            text=sse_body("complete", [record]),
            headers={"content-type": "text/event-stream"},
        )

    return ZeroGpuEvo2AttributionRunner(
        ContentAddressedStore(tmp_path / "artifacts"),
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_completed_attribution_is_never_marked_scientific(tmp_path: Path) -> None:
    runner = build_runner(completed_worker_record(), tmp_path)
    result = runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)

    assert result.scientific_use_allowed is False
    assert result.reference_total_log_likelihood == pytest.approx(-9162.54)
    assert result.agreement_check.spearman_predicted_vs_exact == pytest.approx(0.499)
    assert result.limitations


def test_an_attribution_result_cannot_claim_scientific_use(tmp_path: Path) -> None:
    """The guard is structural, not a convention a caller could override."""

    runner = build_runner(completed_worker_record(), tmp_path)
    result = runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)

    assert result.scientific_use_allowed is False
    with pytest.raises(ValidationError):
        Evo2AttributionResult.model_validate(
            {**result.model_dump(), "scientific_use_allowed": True}
        )


def test_shortlist_is_bounded_and_ranked_by_worst_case(tmp_path: Path) -> None:
    runner = build_runner(completed_worker_record(), tmp_path, shortlist_size=5)
    result = runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)

    assert len(result.ranked_substitutions) == 5
    worst = result.ranked_substitutions[0]
    assert worst.position == 7
    assert worst.worst_case_delta == pytest.approx(-42.0)
    deltas = [item.worst_case_delta for item in result.ranked_substitutions]
    assert deltas == sorted(deltas)


def test_shortlist_omits_a_substitution_to_the_reference_base(tmp_path: Path) -> None:
    runner = build_runner(completed_worker_record(), tmp_path, shortlist_size=4)
    result = runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)

    for item in result.ranked_substitutions:
        assert item.reference not in item.estimated_deltas
        assert len(item.estimated_deltas) == 3


def test_full_estimate_tensor_is_retained_as_an_artifact(tmp_path: Path) -> None:
    runner = build_runner(completed_worker_record(), tmp_path)
    result = runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    retained = json.loads(artifacts.get_bytes(result.output_artifact_digest))
    assert len(retained["substitution_estimates"]["G"]) == WINDOW
    request = json.loads(artifacts.get_bytes(result.input_artifact_digest))
    assert request["input_retained"] is False


def test_off_window_sequence_is_rejected_before_any_call(tmp_path: Path) -> None:
    runner = build_runner(completed_worker_record(), tmp_path)
    with pytest.raises(Evo2AttributionError, match="frozen scoring window"):
        runner.preflight(sequence(4_096))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"execution_status": "FAILED_ATTRIBUTION"}, "did not complete attribution"),
        ({"model_checkpoint": "other/model@deadbeef/x.pt"}, "checkpoint identity"),
        ({"target": "something_else"}, "scoring target"),
        ({"gradient_finite": False}, "finite"),
        ({"sequence_length": 4_096}, "different window length"),
        ({"reference_total_log_likelihood": None}, "reference log-likelihood"),
        ({"substitution_estimates": {"A": [], "C": [], "G": []}}, "each of A, C, G and T"),
        ({"agreement_check": None}, "no agreement check"),
    ],
)
def test_attribution_fails_closed(
    overrides: dict, expected: str, tmp_path: Path
) -> None:
    runner = build_runner(completed_worker_record(**overrides), tmp_path)
    with pytest.raises(Evo2AttributionError, match=expected):
        runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)


def test_a_truncated_estimate_series_is_rejected(tmp_path: Path) -> None:
    estimates = {base: [-0.5] * WINDOW for base in "ACGT"}
    estimates["T"] = [-0.5] * 10
    record = completed_worker_record(substitution_estimates=estimates)
    runner = build_runner(record, tmp_path)

    with pytest.raises(Evo2AttributionError, match="did not cover the window"):
        runner.attribute(sequence(), checkpoint=CHECKPOINT, target=TARGET)
