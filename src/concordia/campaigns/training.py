"""Small, auditable protein-sequence baseline for campaign iteration.

This is an engineering baseline, not a replacement for BioNeMo and not a
scientific validation claim. It deliberately uses interpretable composition
features and a deterministic ridge fit so the training boundary can be tested
without a GPU or private checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np

AMINO_ACIDS = "ARNDCQEGHILKMFPSTWYV"
HYDROPHOBIC = frozenset("AVILMFWY")
CHARGED = frozenset("DEKR")


@dataclass(frozen=True)
class ProteinTrainingExample:
    candidate_id: str
    sequence: str
    value: float


@dataclass(frozen=True)
class FrozenProteinDataset:
    dataset_id: str
    dataset_digest: str
    examples: tuple[ProteinTrainingExample, ...]
    train_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    split_policy: str
    grouping_key: str = "sequence_sha256"


@dataclass(frozen=True)
class ProteinBaselineResult:
    model_id: str
    dataset_id: str
    dataset_digest: str
    coefficients: tuple[float, ...]
    intercept: float
    metrics: dict[str, dict[str, float | int]]
    artifact_digest: str
    scientific_use_allowed: bool = False
    provenance: str = "synthetic_hydrophobic_fraction_demo"


def freeze_protein_dataset(
    dataset_id: str,
    examples: tuple[ProteinTrainingExample, ...],
    *,
    test_fraction: float = 0.2,
    seed: int = 0,
) -> FrozenProteinDataset:
    """Create a deterministic sequence-grouped train/test snapshot."""
    if not dataset_id or not examples:
        raise ValueError("dataset_id and at least one example are required")
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between zero and one")
    if len({example.candidate_id for example in examples}) != len(examples):
        raise ValueError("candidate IDs must be unique")
    normalized = tuple(
        ProteinTrainingExample(
            candidate_id=example.candidate_id,
            sequence=_normalize_sequence(example.sequence),
            value=_finite(example.value),
        )
        for example in examples
    )
    # Split by unique sequence groups, never by rows. This prevents replicate
    # measurements or synonymous candidate records from leaking across folds.
    groups: dict[str, list[ProteinTrainingExample]] = {}
    for example in normalized:
        groups.setdefault(_sequence_group(example.sequence), []).append(example)
    ordered_groups = sorted(
        groups.items(), key=lambda item: hashlib.sha256(f"{seed}:{item[0]}".encode()).hexdigest()
    )
    target = max(1, round(len(normalized) * test_fraction))
    test_groups: list[tuple[str, list[ProteinTrainingExample]]] = []
    test_rows = 0
    for group in ordered_groups:
        if test_rows < target and test_rows + len(group[1]) < len(normalized):
            test_groups.append(group)
            test_rows += len(group[1])
    if not test_groups and len(ordered_groups) > 1:
        test_groups.append(ordered_groups[0])
    test_group_keys = {key for key, _ in test_groups}
    test = tuple(example.candidate_id for key, rows in test_groups for example in rows)
    train = tuple(
        example.candidate_id
        for key, rows in ordered_groups
        if key not in test_group_keys
        for example in rows
    )
    split_policy = f"sequence_group_hash_seeded_v2:{seed}:{test_fraction}"
    payload = {
        "dataset_id": dataset_id,
        "examples": [example.__dict__ for example in normalized],
        "train_ids": train,
        "test_ids": test,
        "split_policy": split_policy,
        "grouping_key": "sequence_sha256",
    }
    digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    return FrozenProteinDataset(
        dataset_id=dataset_id,
        dataset_digest=digest,
        examples=normalized,
        train_ids=train,
        test_ids=test,
        split_policy=split_policy,
    )


def train_protein_baseline(
    dataset: FrozenProteinDataset, *, l2: float = 1.0
) -> ProteinBaselineResult:
    """Fit ridge regression and return a content-addressed result manifest."""
    if l2 <= 0 or not math.isfinite(l2):
        raise ValueError("l2 must be finite and positive")
    by_id = {example.candidate_id: example for example in dataset.examples}
    train = [by_id[candidate_id] for candidate_id in dataset.train_ids]
    if not train:
        raise ValueError("frozen dataset has no training examples")
    x_train = np.asarray([sequence_features(example.sequence) for example in train], dtype=float)
    y_train = np.asarray([example.value for example in train], dtype=float)
    design = np.column_stack([np.ones(len(x_train)), x_train])
    penalty = np.eye(design.shape[1]) * l2
    penalty[0, 0] = 0
    weights = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    metrics = {
        "train": _metrics(train, weights),
        "test": _metrics([by_id[candidate_id] for candidate_id in dataset.test_ids], weights),
    }
    model_id = "protein_composition_ridge_v1"
    manifest = {
        "schema_version": 1,
        "model_id": model_id,
        "dataset_id": dataset.dataset_id,
        "dataset_digest": dataset.dataset_digest,
        "split_policy": dataset.split_policy,
        "l2": l2,
        "intercept": float(weights[0]),
        "coefficients": [float(value) for value in weights[1:]],
        "metrics": metrics,
        "scientific_use_allowed": False,
        "provenance": "synthetic_hydrophobic_fraction_demo",
    }
    artifact_digest = hashlib.sha256(_canonical_json(manifest).encode()).hexdigest()
    return ProteinBaselineResult(
        model_id=model_id,
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.dataset_digest,
        coefficients=tuple(float(value) for value in weights[1:]),
        intercept=float(weights[0]),
        metrics=metrics,
        artifact_digest=artifact_digest,
        provenance="synthetic_hydrophobic_fraction_demo",
    )


def sequence_features(sequence: str) -> tuple[float, ...]:
    normalized = _normalize_sequence(sequence)
    length = len(normalized)
    counts = tuple(normalized.count(residue) / length for residue in AMINO_ACIDS)
    return (
        math.log1p(length),
        normalized.count("G") / length,
        normalized.count("P") / length,
        sum(residue in HYDROPHOBIC for residue in normalized) / length,
        sum(residue in CHARGED for residue in normalized) / length,
        *counts,
    )


def predict_protein_baseline(result: ProteinBaselineResult, sequence: str) -> float:
    """Predict one sequence while keeping the model explicitly non-scientific."""
    return float(
        result.intercept
        + np.asarray(sequence_features(sequence)) @ np.asarray(result.coefficients)
    )


def training_mean_baseline(dataset: FrozenProteinDataset) -> float:
    by_id = {example.candidate_id: example for example in dataset.examples}
    values = [by_id[candidate_id].value for candidate_id in dataset.train_ids]
    if not values:
        raise ValueError("frozen dataset has no training examples")
    return float(sum(values) / len(values))


def baseline_comparison(
    result: ProteinBaselineResult, dataset: FrozenProteinDataset
) -> dict[str, object]:
    """Return a transparent model-vs-constant comparison and uncertainty proxy."""
    by_id = {example.candidate_id: example for example in dataset.examples}
    test = [by_id[candidate_id] for candidate_id in dataset.test_ids]
    mean_prediction = training_mean_baseline(dataset)
    if not test:
        return {"status": "insufficient_evidence", "reason": "no held-out examples"}
    mean_errors = [mean_prediction - example.value for example in test]
    model_rmse = float(result.metrics["test"].get("rmse", float("nan")))
    mean_rmse = float(math.sqrt(sum(error * error for error in mean_errors) / len(mean_errors)))
    return {
        "status": "model_beats_constant" if model_rmse < mean_rmse else "insufficient_evidence",
        "model_test_rmse": model_rmse,
        "constant_test_rmse": mean_rmse,
        "test_n": len(test),
        "uncertainty_proxy": model_rmse,
        "scientific_use_allowed": False,
    }


def _metrics(examples: list[ProteinTrainingExample], weights: np.ndarray) -> dict[str, float | int]:
    if not examples:
        return {"n": 0, "mae": float("nan"), "rmse": float("nan")}
    features = np.asarray([sequence_features(example.sequence) for example in examples])
    labels = np.asarray([example.value for example in examples], dtype=float)
    predictions = np.column_stack([np.ones(len(features)), features]) @ weights
    errors = predictions - labels
    return {
        "n": len(examples),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
    }


def _normalize_sequence(sequence: str) -> str:
    normalized = "".join(sequence.upper().split())
    if not normalized or any(residue not in AMINO_ACIDS for residue in normalized):
        raise ValueError("sequence contains unsupported protein residues")
    return normalized


def _sequence_group(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("training values must be finite")
    return float(value)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "FrozenProteinDataset",
    "ProteinBaselineResult",
    "ProteinTrainingExample",
    "freeze_protein_dataset",
    "baseline_comparison",
    "predict_protein_baseline",
    "sequence_features",
    "training_mean_baseline",
    "train_protein_baseline",
]
