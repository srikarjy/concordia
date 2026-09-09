"""Build and persist frozen evidence packets from predictor artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from concordia.evidence.schema import (
    Attribution,
    EvidencePacket,
    ExplanationEvidence,
    PredictionEvidence,
)


def _top_attributions(
    values: np.ndarray, k: int = 10
) -> tuple[tuple[Attribution, ...], tuple[Attribution, ...]]:
    positive_indices = np.flatnonzero(values > 0)
    negative_indices = np.flatnonzero(values < 0)
    positive_indices = positive_indices[np.argsort(values[positive_indices])[::-1]][:k]
    negative_indices = negative_indices[np.argsort(values[negative_indices])][:k]
    positive = tuple(
        Attribution(
            feature_id=f"bit_{index:04d}",
            value=float(values[index]),
            rank=rank,
            direction="positive",
        )
        for rank, index in enumerate(positive_indices, start=1)
    )
    negative = tuple(
        Attribution(
            feature_id=f"bit_{index:04d}",
            value=float(values[index]),
            rank=rank,
            direction="negative",
        )
        for rank, index in enumerate(negative_indices, start=1)
    )
    return positive, negative


def packet_from_row(
    row: pd.Series,
    attribution_values: np.ndarray | None,
    shap_version: str = "unknown",
    documents: Iterable[dict[str, object]] = (),
) -> EvidencePacket:
    explanation = None
    if attribution_values is not None:
        values = np.asarray(attribution_values, dtype=float)
        if values.ndim != 1 or not np.isfinite(values).all():
            raise ValueError("Attribution values must be a finite one-dimensional array")
        top_positive, top_negative = _top_attributions(values)
        explanation = ExplanationEvidence(
            method="tree_shap",
            version=shap_version,
            output="positive_class_probability",
            feature_count=int(values.size),
            attributions=tuple(float(value) for value in values),
            top_positive=top_positive,
            top_negative=top_negative,
        )
    return EvidencePacket(
        packet_id=f"{row['molecule_id']}:control",
        molecule_id=str(row["molecule_id"]),
        canonical_smiles=str(row["canonical_smiles"]),
        prediction=PredictionEvidence(
            model_id=str(row["model_id"]),
            assay=str(row["assay"]),
            probability=float(row["prediction_probability"]),
            predicted_label=int(row["prediction"]),
        ),
        explanation=explanation,
        documents=tuple(documents),
    )


def write_packet(packet: EvidencePacket, directory: str | Path) -> Path:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{packet.content_hash()}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(packet.canonical_json() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read_packet(path: str | Path) -> EvidencePacket:
    return EvidencePacket.model_validate_json(Path(path).read_text(encoding="utf-8"))
