"""TreeSHAP generation for the Random Forest baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from concordia.artifacts import environment_metadata, sha256_file, write_json
from concordia.config import FingerprintConfig
from concordia.predictors.fingerprints import morgan_fingerprints


def _positive_class_values(values: Any, positive_index: int) -> np.ndarray:
    """Normalize SHAP's list/array return forms across supported versions."""
    if isinstance(values, list):
        if len(values) <= positive_index:
            raise ValueError("SHAP did not return the requested positive class")
        values = values[positive_index]
    array = np.asarray(values, dtype=float)
    if array.ndim == 3:
        if array.shape[-1] <= positive_index:
            raise ValueError("SHAP did not return the requested positive class")
        array = array[:, :, positive_index]
    if array.ndim != 2:
        raise ValueError(f"Unexpected SHAP value shape: {array.shape}")
    return array


def generate_tree_shap(
    model_path: str | Path,
    molecules_path: str | Path,
    output_directory: str | Path,
    background_size: int = 128,
    limit: int | None = None,
) -> dict[str, str | int | float | None]:
    """Generate positive-class probability attributions and validate additivity."""
    try:
        import shap
    except ImportError as error:
        raise RuntimeError("Install the optional xai dependency first") from error

    bundle = joblib.load(model_path)
    model = bundle["model"]
    fp_values = bundle["fingerprint"]
    fp_config = FingerprintConfig(
        radius=int(fp_values["radius"]),
        n_bits=int(fp_values["n_bits"]),
        include_chirality=bool(fp_values["include_chirality"]),
    )
    molecules = pd.read_csv(molecules_path).sort_values("molecule_id").reset_index(drop=True)
    if limit is not None:
        molecules = molecules.head(limit).copy()
    features = morgan_fingerprints(molecules["canonical_smiles"].tolist(), fp_config)
    background_frame = pd.read_csv(molecules_path)
    background_frame = (
        background_frame[background_frame["split"] == "train"]
        .sort_values("molecule_id")
        .head(background_size)
    )
    background = morgan_fingerprints(background_frame["canonical_smiles"].tolist(), fp_config)
    positive_index = list(model.classes_).index(1)
    explainer = shap.TreeExplainer(
        model,
        data=background,
        feature_perturbation="interventional",
        model_output="probability",
    )
    values = _positive_class_values(
        explainer.shap_values(features, check_additivity=False), positive_index
    )
    probabilities = model.predict_proba(features)[:, positive_index]
    expected_value = float(np.asarray(explainer.expected_value).reshape(-1)[positive_index])
    reconstruction_error = expected_value + values.sum(axis=1) - probabilities
    max_error = float(np.max(np.abs(reconstruction_error))) if len(values) else 0.0
    if not np.isfinite(values).all() or max_error > 1e-4:
        raise ValueError(f"SHAP output failed validation; max reconstruction error={max_error}")

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    values_path = output / "shap_values.npy"
    records_path = output / "explanations.jsonl"
    manifest_path = output / "manifest.json"
    np.save(values_path, values)
    with records_path.open("w", encoding="utf-8") as handle:
        for row_index, row in molecules.iterrows():
            record = {
                "row_index": int(row_index),
                "molecule_id": row["molecule_id"],
                "model_id": row["model_id"],
                "assay": row["assay"],
                "prediction_probability": float(probabilities[row_index]),
                "expected_value": expected_value,
                "reconstruction_error": float(reconstruction_error[row_index]),
            }
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    manifest = {
        "schema_version": 1,
        "stage": "tree_shap",
        "model_path": str(model_path),
        "model_sha256": sha256_file(model_path),
        "molecules_path": str(molecules_path),
        "molecules_sha256": sha256_file(molecules_path),
        "background_size": len(background),
        "explained_rows": len(molecules),
        "feature_count": fp_config.n_bits,
        "max_reconstruction_error": max_error,
        "shap_version": shap.__version__,
        "environment": environment_metadata(),
        "artifacts": {
            "values": {"path": values_path.name, "sha256": sha256_file(values_path)},
            "records": {"path": records_path.name, "sha256": sha256_file(records_path)},
        },
    }
    write_json(manifest_path, manifest)
    return {
        "manifest": str(manifest_path),
        "explained_rows": len(molecules),
        "max_error": max_error,
    }


def validate_tree_shap(manifest_path: str | Path) -> dict[str, str | int | float]:
    """Validate hashes, dimensions, finiteness, and reconstruction metadata."""
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    base = manifest_file.parent
    values_path = base / manifest["artifacts"]["values"]["path"]
    records_path = base / manifest["artifacts"]["records"]["path"]
    if sha256_file(values_path) != manifest["artifacts"]["values"]["sha256"]:
        raise ValueError("SHAP values checksum does not match manifest")
    if sha256_file(records_path) != manifest["artifacts"]["records"]["sha256"]:
        raise ValueError("SHAP records checksum does not match manifest")
    values = np.load(values_path, allow_pickle=False)
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    if values.ndim != 2 or len(records) != values.shape[0]:
        raise ValueError("SHAP values and records are not aligned")
    if values.shape[1] != int(manifest["feature_count"]):
        raise ValueError("SHAP feature count does not match manifest")
    errors = np.asarray([float(record["reconstruction_error"]) for record in records])
    if not np.isfinite(values).all() or not np.isfinite(errors).all():
        raise ValueError("SHAP artifact contains non-finite values")
    max_error = float(np.max(np.abs(errors))) if len(errors) else 0.0
    if max_error > 1e-4:
        raise ValueError(f"SHAP reconstruction error exceeds tolerance: {max_error}")
    return {
        "manifest": str(manifest_file),
        "explained_rows": int(values.shape[0]),
        "feature_count": int(values.shape[1]),
        "max_reconstruction_error": max_error,
    }
