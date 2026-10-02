"""Self-contained causal-likelihood scoring for the ZeroGPU forward worker.

This module intentionally does not import the main ``concordia`` package: the
worker is a separate deployable unit (its own ``requirements.txt``, no access
to the main repository at runtime). The algorithm here must stay numerically
identical to ``concordia.genomics.evo2_protocol.score_causal_logits`` — that
is enforced by a parity test in the main repository
(``tests/unit/test_evo2_worker_scoring_parity.py``), not by a shared import.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

EXPECTED_SEQUENCE_LENGTH = 8_192
EXPECTED_SCORED_TOKEN_COUNT = EXPECTED_SEQUENCE_LENGTH - 1


def validate_protocol_sequence(sequence: str) -> str | None:
    """Return an error message, or None if the sequence satisfies the frozen protocol."""

    if not isinstance(sequence, str):
        return "sequence must be a string"
    normalized = sequence.strip().upper()
    if len(normalized) != EXPECTED_SEQUENCE_LENGTH:
        return (
            f"sequence must be exactly {EXPECTED_SEQUENCE_LENGTH} bases "
            f"(received {len(normalized)})"
        )
    invalid = sorted(set(normalized) - set("ACGT"))
    if invalid:
        return f"sequence contains invalid bases: {''.join(invalid)}"
    return None


def score_causal_logits(logits: np.ndarray, token_ids: Sequence[int]) -> dict[str, Any]:
    """Score token i+1 from logits at i, matching the pinned official Evo2 scorer.

    Duplicated from ``concordia.genomics.evo2_protocol.score_causal_logits`` by
    necessity (see module docstring); keep any change mirrored there and rerun
    the parity test.
    """

    values = np.asarray(logits)
    tokens = np.asarray(token_ids, dtype=np.int64)
    if values.ndim != 2:
        raise ValueError("logits must have shape (sequence_length, vocabulary_size)")
    if tokens.ndim != 1 or tokens.shape[0] != values.shape[0]:
        raise ValueError("token IDs must match the logits sequence dimension")
    if values.shape[0] < 2 or values.shape[1] < 1:
        raise ValueError("logits are too small for causal scoring")
    if not np.isfinite(values).all():
        raise ValueError("logits contain non-finite values")
    targets = tokens[1:]
    if np.any(targets < 0) or np.any(targets >= values.shape[1]):
        raise ValueError("target token ID is outside the logits vocabulary")

    predictors = values[:-1].astype(np.float64, copy=False)
    maxima = predictors.max(axis=1)
    log_normalizers = maxima + np.log(
        np.exp(predictors - maxima[:, np.newaxis]).sum(axis=1)
    )
    target_logits = predictors[np.arange(targets.shape[0]), targets]
    log_probabilities = target_logits - log_normalizers
    total = float(log_probabilities.sum(dtype=np.float64))
    mean = float(total / log_probabilities.shape[0])
    if not all(math.isfinite(value) for value in (total, mean, *log_probabilities)):
        raise ValueError("likelihood computation produced non-finite values")
    return {
        "scored_token_count": int(log_probabilities.shape[0]),
        "sum_log_likelihood": total,
        "mean_log_likelihood": mean,
        "target_token_log_probabilities": [float(value) for value in log_probabilities],
    }
