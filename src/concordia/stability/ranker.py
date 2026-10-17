"""Single production ranking implementation for measured stability."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

RANKER_NAME = "ThermoMPNN + one-hot rank average"
RANKER_ARTIFACT_PATH = Path("data/processed/tsuboyama_production_ranker.json")


def rank_average_scores(
    candidate_ids: list[str],
    thermompnn_scores: dict[str, float],
    one_hot_scores: dict[str, float],
) -> dict[str, float]:
    """Return higher-is-better rank-average scores for the supplied candidates."""
    missing = [
        variant_id
        for variant_id in candidate_ids
        if variant_id not in thermompnn_scores or variant_id not in one_hot_scores
    ]
    if missing:
        raise ValueError(f"production ranker artifact lacks candidates: {missing[:5]}")
    thermo = [thermompnn_scores[variant_id] for variant_id in candidate_ids]
    one_hot = [one_hot_scores[variant_id] for variant_id in candidate_ids]
    thermo_order = {value: index for index, value in enumerate(sorted(thermo))}
    one_hot_order = {value: index for index, value in enumerate(sorted(one_hot))}
    return {
        variant_id: float(thermo_order[thermo_value] + one_hot_order[one_hot_value])
        for variant_id, thermo_value, one_hot_value in zip(
            candidate_ids, thermo, one_hot, strict=True
        )
    }


def load_ranker_artifact(path: Path = RANKER_ARTIFACT_PATH) -> dict[str, Any]:
    """Load and validate the deterministic, holdout-independent ranker artifact."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("ranker") != RANKER_NAME:
        raise ValueError("production ranker artifact does not identify the selected ranker")
    if payload.get("holdout_used") is not False:
        raise ValueError("production ranker artifact must state that the holdout was unused")
    recorded_digest = payload.get("artifact_digest")
    unsigned = {key: value for key, value in payload.items() if key != "artifact_digest"}
    computed_digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    if recorded_digest != computed_digest:
        raise ValueError("production ranker artifact digest does not match its contents")
    for field in ("thermompnn_scores", "one_hot_scores"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(f"production ranker artifact is missing {field}")
    return cast(dict[str, Any], payload)


__all__ = ["RANKER_ARTIFACT_PATH", "RANKER_NAME", "load_ranker_artifact", "rank_average_scores"]
