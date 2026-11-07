"""Cache reuse must retain the computation identity that created it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from scripts import evaluate_tsuboyama_predictor as predictor

CHECKPOINT = "facebook/esm2_t33_650M_UR50D"


def _variants() -> list[Any]:
    return [SimpleNamespace(variant_id="v1", position=1)]


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"variant_id": ["v1"], "position": [1], "f0": [1.0]})


def test_unproven_matching_cache_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "embeddings.parquet"
    _frame().to_parquet(cache, index=False)
    monkeypatch.setattr(predictor, "EMBEDDING_CACHE", cache)

    with pytest.raises(RuntimeError, match="fresh extraction"):
        monkeypatch.setattr(
            predictor,
            "extract_site_embeddings",
            lambda *_: (_ for _ in ()).throw(RuntimeError("fresh extraction required")),
        )
        predictor.load_or_extract("ACDEFGHIKLMNPQRSTVWY", _variants())


def test_sidecar_binds_cache_to_sequence_mapping_and_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "embeddings.parquet"
    _frame().to_parquet(cache, index=False)
    monkeypatch.setattr(predictor, "EMBEDDING_CACHE", cache)
    sequence = "ACDEFGHIKLMNPQRSTVWY"
    sidecar = {
        "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        "variant_positions": {"v1": 1},
        "checkpoint": CHECKPOINT,
        "checkpoint_commit": predictor.CHECKPOINT_COMMIT,
        "checkpoint_file_sha256": {"model.safetensors": "test-only"},
    }
    predictor._cache_metadata_path(cache).write_text(json.dumps(sidecar))
    monkeypatch.setattr(
        predictor,
        "extract_site_embeddings",
        lambda *_: (_ for _ in ()).throw(AssertionError("verified cache should be reused")),
    )

    frame, metadata = predictor.load_or_extract(sequence, _variants())

    assert frame["f0"].iloc[0] == 1.0
    assert metadata["cache"] == "reused_verified_sidecar"


def test_sidecar_with_wrong_sequence_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "embeddings.parquet"
    _frame().to_parquet(cache, index=False)
    monkeypatch.setattr(predictor, "EMBEDDING_CACHE", cache)
    predictor._cache_metadata_path(cache).write_text(
        json.dumps(
            {
                "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
                "sequence_sha256": "0" * 64,
                "variant_positions": {"v1": 1},
                "checkpoint": CHECKPOINT,
                "checkpoint_commit": predictor.CHECKPOINT_COMMIT,
                "checkpoint_file_sha256": {"model.safetensors": "test-only"},
            }
        )
    )
    monkeypatch.setattr(
        predictor,
        "extract_site_embeddings",
        lambda *_: (_ for _ in ()).throw(RuntimeError("fresh extraction required")),
    )

    with pytest.raises(RuntimeError, match="fresh extraction"):
        predictor.load_or_extract("ACDEFGHIKLMNPQRSTVWY", _variants())
