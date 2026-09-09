"""End-to-end NR-AhR Random Forest baseline."""

from __future__ import annotations

from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    roc_auc_score,
)

from concordia.artifacts import (
    command_metadata,
    environment_metadata,
    git_metadata,
    sha256_file,
    write_json,
)
from concordia.config import BaselineConfig
from concordia.predictors.data import prepare_tox21
from concordia.predictors.fingerprints import morgan_fingerprints
from concordia.predictors.split import scaffold_split


def _metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    predictions = (probabilities >= 0.5).astype(int)
    result: dict[str, Any] = {
        "n": int(len(labels)),
        "n_positive": int(labels.sum()),
        "positive_fraction": float(labels.mean()),
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "confusion_matrix": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
        "threshold": 0.5,
    }
    if len(np.unique(labels)) == 2:
        result["roc_auc"] = float(roc_auc_score(labels, probabilities))
        result["average_precision"] = float(average_precision_score(labels, probabilities))
    else:
        result["roc_auc"] = None
        result["average_precision"] = None
    return result


def train_baseline(config: BaselineConfig) -> dict[str, Any]:
    """Train, evaluate, and persist a configured molecular baseline."""
    prepared = prepare_tox21(
        config.dataset.raw_path,
        assay=config.dataset.assay,
        include_chirality=config.fingerprint.include_chirality,
    )
    split_frame = scaffold_split(prepared.molecules, config.split)
    features = morgan_fingerprints(
        split_frame["canonical_smiles"].tolist(), config.fingerprint
    )
    labels = split_frame["label"].to_numpy(dtype=np.uint8)

    train_mask = split_frame["split"].eq("train").to_numpy()
    if len(np.unique(labels[train_mask])) != 2:
        raise ValueError("Training split must contain both classes")
    model = RandomForestClassifier(
        n_estimators=config.model.n_estimators,
        class_weight=config.model.class_weight,
        random_state=config.model.seed,
        n_jobs=config.model.n_jobs,
    )
    model.fit(features[train_mask], labels[train_mask])

    probabilities = model.predict_proba(features)[:, list(model.classes_).index(1)]
    split_frame["assay"] = config.dataset.assay
    split_frame["model_id"] = (
        f"random_forest:morgan-r{config.fingerprint.radius}-b{config.fingerprint.n_bits}"
        f":seed={config.model.seed}"
    )
    split_frame["prediction_probability"] = probabilities
    split_frame["prediction"] = (probabilities >= 0.5).astype(int)

    metrics = {
        name: _metrics(
            labels[split_frame["split"].eq(name).to_numpy()],
            probabilities[split_frame["split"].eq(name).to_numpy()],
        )
        for name in ("train", "validation", "test")
    }

    output = config.artifact_directory
    output.mkdir(parents=True, exist_ok=True)
    split_path = output / "molecules.csv"
    exclusions_path = output / "exclusions.csv"
    model_path = output / "model.joblib"
    metrics_path = output / "metrics.json"
    manifest_path = output / "manifest.json"
    split_frame.to_csv(split_path, index=False)
    prepared.exclusions.to_csv(exclusions_path, index=False)
    joblib.dump(
        {
            "model": model,
            "fingerprint": config.raw["fingerprint"],
            "assay": config.dataset.assay,
            "class_order": [int(item) for item in model.classes_],
        },
        model_path,
    )
    write_json(metrics_path, metrics)

    manifest = {
        "schema_version": 1,
        "stage": "baseline_predictor",
        "dataset": {
            "name": config.dataset.name,
            "assay": config.dataset.assay,
            "source_url": config.dataset.url,
            "raw_path": str(config.dataset.raw_path),
            "raw_sha256": sha256_file(config.dataset.raw_path),
        },
        "configuration": config.raw,
        "configuration_path": str(config.source_path),
        "counts": {
            "molecules": int(len(split_frame)),
            "excluded_rows": int(len(prepared.exclusions)),
            "splits": {
                key: int(value)
                for key, value in split_frame["split"].value_counts().sort_index().items()
            },
        },
        "environment": environment_metadata(),
        "git": git_metadata(),
        "command": command_metadata(),
        "artifacts": {
            "molecules": {"path": split_path.name, "sha256": sha256_file(split_path)},
            "exclusions": {
                "path": exclusions_path.name,
                "sha256": sha256_file(exclusions_path),
            },
            "model": {"path": model_path.name, "sha256": sha256_file(model_path)},
            "metrics": {"path": metrics_path.name, "sha256": sha256_file(metrics_path)},
        },
        "notes": [
            "The 0.5 classification threshold was not tuned.",
            "Ring-free molecules share the empty Murcko scaffold and remain in one split.",
            "These are predictor metrics, not Concordia LLM robustness findings.",
        ],
    }
    write_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "metrics": metrics}
