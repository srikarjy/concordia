"""The ZeroGPU worker duplicates causal-likelihood scoring (no concordia import
is possible from its deployment). This test is the only thing keeping that
duplicate numerically identical to ``concordia.genomics.evo2_protocol``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from concordia.genomics.evo2_protocol import score_causal_logits as reference_scorer

WORKER_SCORING_PATH = (
    Path(__file__).resolve().parents[2] / "deploy" / "hf-evo2-worker" / "scoring.py"
)


def _load_worker_scoring_module():
    spec = importlib.util.spec_from_file_location(
        "hf_evo2_worker_scoring", WORKER_SCORING_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


worker_scoring = _load_worker_scoring_module()


@pytest.mark.parametrize("seed", [0, 1, 7, 42])
def test_worker_scoring_matches_reference_implementation(seed: int) -> None:
    rng = np.random.default_rng(seed)
    sequence_length, vocabulary_size = 32, 512
    logits = rng.normal(size=(sequence_length, vocabulary_size)).astype(np.float64)
    token_ids = rng.integers(0, vocabulary_size, size=sequence_length).tolist()

    reference = reference_scorer(logits, token_ids)
    worker = worker_scoring.score_causal_logits(logits, token_ids)

    assert worker["scored_token_count"] == reference.scored_token_count
    assert worker["sum_log_likelihood"] == pytest.approx(reference.sum_log_likelihood)
    assert worker["mean_log_likelihood"] == pytest.approx(reference.mean_log_likelihood)
    assert worker["target_token_log_probabilities"] == pytest.approx(
        list(reference.target_token_log_probabilities)
    )


def test_validate_protocol_sequence_enforces_exact_frozen_window() -> None:
    assert worker_scoring.validate_protocol_sequence("ACGT" * 2048) is None
    assert worker_scoring.validate_protocol_sequence("ACGT") is not None
    assert worker_scoring.validate_protocol_sequence("N" * 8192) is not None
    assert worker_scoring.validate_protocol_sequence("ACGT" * 2047) is not None
