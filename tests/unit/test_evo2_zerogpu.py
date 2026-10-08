from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
from concordia.genomics.evo2_real import RealEvo2Scorer
from concordia.genomics.evo2_zerogpu import Evo2ForwardExecutionError, ZeroGpuEvo2ForwardRunner
from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore

CHECKPOINT = "arcinstitute/evo2_7b@bda0089f92582d5baabf0f22d9fc85f3588f6b58/evo2_7b.pt"
TARGET = "mean_next_base_log_likelihood"


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


def sequence(length: int = 8_192) -> GenomicSequence:
    return GenomicSequence(
        sequence_id="hbb:test-window", sequence="ACGT" * (length // 4), strand="+"
    )


def sse_body(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def completed_worker_record(**overrides: object) -> dict:
    record = {
        "schema_version": 1,
        "model_checkpoint": CHECKPOINT,
        "target": TARGET,
        "execution_status": "COMPLETED",
        "sequence_length": 8192,
        "scored_token_count": 8191,
        "sum_log_likelihood": -100.0,
        "mean_log_likelihood": -0.0122,
        "target_token_log_probabilities": [-0.01] * 8191,
        "scientific_use_allowed": False,
    }
    record.update(overrides)
    return record


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_successful_in_scope_forward_pass_is_accepted_by_real_scorer(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/call/score_sequence"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        return httpx.Response(
            200,
            text=sse_body("complete", [completed_worker_record()]),
            headers={"content-type": "text/event-stream"},
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = ZeroGpuEvo2ForwardRunner(
        artifacts,
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=mock_transport(handler),
    )
    scorer = RealEvo2Scorer(runner, checkpoint=CHECKPOINT, target=TARGET)
    result = scorer.score(sequence())

    assert result.execution_mode == "real"
    assert result.scientific_use_allowed is True
    assert result.model_id == CHECKPOINT
    assert artifacts.get_bytes(result.input_artifact_digest)
    assert artifacts.get_bytes(result.output_artifact_digest)
    assert result.runtime_metadata["target_token_log_probabilities"] == [-0.01] * 8191
    retained_request = json.loads(artifacts.get_bytes(result.input_artifact_digest))
    assert retained_request["input_retained"] is False
    assert retained_request["input_sequence_length"] == 8_192
    assert sequence().sequence not in json.dumps(retained_request)


def test_wrong_scored_token_count_is_rejected_as_out_of_scope(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/call/score_sequence"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        return httpx.Response(
            200,
            text=sse_body("complete", [completed_worker_record(scored_token_count=100)]),
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = ZeroGpuEvo2ForwardRunner(
        artifacts,
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=mock_transport(handler),
    )
    scorer = RealEvo2Scorer(runner, checkpoint=CHECKPOINT, target=TARGET)
    with pytest.raises(ValueError, match="fixture or synthetic"):
        scorer.score(sequence())


def test_worker_failure_status_raises_without_scoring(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/call/score_sequence"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        return httpx.Response(
            200,
            text=sse_body(
                "complete",
                [
                    {
                        "schema_version": 1,
                        "model_checkpoint": CHECKPOINT,
                        "target": TARGET,
                        "execution_status": "FAILED_MODEL_LOAD",
                        "error": "RuntimeError: model load failed",
                        "scientific_use_allowed": False,
                    }
                ],
            ),
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = ZeroGpuEvo2ForwardRunner(
        artifacts,
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=mock_transport(handler),
    )
    with pytest.raises(Evo2ForwardExecutionError, match="FAILED_MODEL_LOAD"):
        runner.score(sequence(), checkpoint=CHECKPOINT, target=TARGET)


def test_checkpoint_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/call/score_sequence"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        return httpx.Response(
            200,
            text=sse_body(
                "complete", [completed_worker_record(model_checkpoint="wrong/checkpoint")]
            ),
        )

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = ZeroGpuEvo2ForwardRunner(
        artifacts,
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=mock_transport(handler),
    )
    with pytest.raises(Evo2ForwardExecutionError, match="checkpoint identity"):
        runner.score(sequence(), checkpoint=CHECKPOINT, target=TARGET)


def test_wrong_sequence_length_is_rejected_before_any_request(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request should be made for an invalid length")

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = ZeroGpuEvo2ForwardRunner(
        artifacts,
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=mock_transport(handler),
    )
    with pytest.raises(Evo2ForwardExecutionError, match="sequence length"):
        runner.score(sequence(length=16), checkpoint=CHECKPOINT, target=TARGET)


def test_worker_error_event_is_surfaced(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/call/score_sequence"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        return httpx.Response(200, text=sse_body("error", "GPU allocation timed out"))

    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    runner = ZeroGpuEvo2ForwardRunner(
        artifacts,
        space_url="https://example.hf.space",
        scoring=scoring_semantics(),
        transport=mock_transport(handler),
    )
    with pytest.raises(Evo2ForwardExecutionError, match="error event"):
        runner.score(sequence(), checkpoint=CHECKPOINT, target=TARGET)
