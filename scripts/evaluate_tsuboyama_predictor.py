"""Run the frozen ESM-2 site-embedding predictor for Gate 3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

try:  # Supports both ``python scripts/...`` and package-based regression tests.
    from scripts.evaluate_tsuboyama_baselines import (
        CHECKPOINT,
        MANIFEST,
        Variant,
        load_manifest,
        load_rows,
        metric_row,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script invocation fallback
    from evaluate_tsuboyama_baselines import (  # type: ignore[no-redef]
        CHECKPOINT,
        MANIFEST,
        Variant,
        load_manifest,
        load_rows,
        metric_row,
    )
from scipy.spatial.distance import pdist
from sklearn.decomposition import PCA
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler

from concordia.runtime.esm_checkpoint import ESM2_REVISION, load_esm2
from concordia.stability.assets import load_trusted_manifest

FROZEN_EMBEDDING_CACHE = Path("data/processed/tsuboyama_esm2_site_embeddings.parquet")
EMBEDDING_CACHE = FROZEN_EMBEDDING_CACHE
OUTPUT = Path("data/processed/tsuboyama_predictor_metrics.json")
CHECKPOINT_COMMIT = ESM2_REVISION
SEED = 1729
BATCH_SIZE = 8
PCA_COMPONENTS = 50


def mutate(sequence: str, position: int, mutant: str) -> str:
    return sequence[: position - 1] + mutant + sequence[position:]


def extract_site_embeddings(
    sequence: str, variants: list[Variant]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Cached-feature evaluation and uncertainty tests do not need model runtimes.
    # Install the `esm` extra only when computing new embeddings.
    import torch
    from transformers import EsmModel

    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    tokenizer, model, source_digests = load_esm2(EsmModel)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)

    with torch.no_grad():
        wt_tokens = tokenizer(sequence, return_tensors="pt")["input_ids"].to(device)
        wt_hidden = model(wt_tokens).last_hidden_state[0].detach().cpu().numpy()
    wt_sites = {index + 1: wt_hidden[index + 1] for index in range(len(sequence))}

    validation = variants[:5]
    validation_sequences = [mutate(sequence, row.position, row.mutant) for row in validation]
    validation_tokens = tokenizer(
        validation_sequences, return_tensors="pt", padding=True
    )["input_ids"]
    with torch.no_grad():
        mps_hidden = model(validation_tokens.to(device)).last_hidden_state.detach().cpu()
    model.to("cpu")
    with torch.no_grad():
        cpu_hidden = model(validation_tokens).last_hidden_state.detach().cpu()
    mps_cpu_max_abs_diff = float(torch.max(torch.abs(mps_hidden - cpu_hidden)))
    model.to(device)

    vectors: list[np.ndarray] = []
    ids: list[str] = []
    positions: list[int] = []
    for start in range(0, len(variants), BATCH_SIZE):
        batch = variants[start : start + BATCH_SIZE]
        sequences = [mutate(sequence, row.position, row.mutant) for row in batch]
        tokens = tokenizer(sequences, return_tensors="pt", padding=True)["input_ids"].to(device)
        with torch.no_grad():
            hidden = model(tokens).last_hidden_state.detach().cpu().numpy()
        for index, row in enumerate(batch):
            mutant_site = hidden[index, row.position]
            vectors.append(np.concatenate((mutant_site, wt_sites[row.position])).astype(np.float32))
            ids.append(row.variant_id)
            positions.append(row.position)

    matrix = np.vstack(vectors)
    frame = pd.DataFrame(matrix, columns=[f"f{index}" for index in range(matrix.shape[1])])
    frame.insert(0, "position", positions)
    frame.insert(0, "variant_id", ids)
    metadata = {
        "checkpoint": CHECKPOINT,
        "checkpoint_commit": CHECKPOINT_COMMIT,
        "checkpoint_file_sha256": source_digests,
        "feature_definition": (
            "mutant-site last hidden state concatenated with "
            "wild-type-site last hidden state"
        ),
        "embedding_dimension": int(matrix.shape[1]),
        "device": str(device),
        "mps_available": bool(torch.backends.mps.is_available()),
        "mps_cpu_max_abs_diff_first_5": mps_cpu_max_abs_diff,
        "batch_size": BATCH_SIZE,
        "seed": SEED,
    }
    return frame, metadata


def _file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _cache_metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".provenance.json")


def _expected_mapping(sequence: str, variants: list[Variant]) -> dict[str, object]:
    return {
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        "variant_positions": {row.variant_id: row.position for row in variants},
    }


def _validate_frame(frame: pd.DataFrame, variants: list[Variant]) -> None:
    expected = {row.variant_id: row.position for row in variants}
    required = {"variant_id", "position"}
    features = [column for column in frame.columns if column.startswith("f")]
    if not required.issubset(frame.columns) or not features:
        raise ValueError(
            "embedding cache lacks the required identifier, position, or feature columns"
        )
    if len(frame) != len(expected) or frame["variant_id"].duplicated().any():
        raise ValueError("embedding cache does not have one row per requested variant")
    observed = {str(row.variant_id): int(row.position) for row in frame.itertuples(index=False)}
    if observed != expected:
        raise ValueError("embedding cache IDs or positions differ from the requested mapping")
    if any(not np.issubdtype(frame[column].dtype, np.number) for column in features):
        raise ValueError("embedding cache contains a nonnumeric feature column")


def _frozen_cache_metadata(
    path: Path, sequence: str, variants: list[Variant]
) -> dict[str, Any] | None:
    """Validate the one reviewed historical cache against its pinned asset manifest."""
    root = Path(__file__).resolve().parent.parent
    canonical = root / FROZEN_EMBEDDING_CACHE
    if path.resolve() != canonical.resolve():
        return None
    manifest = load_trusted_manifest(root)
    record = manifest["files"].get(str(FROZEN_EMBEDDING_CACHE))
    if not isinstance(record, dict) or _file_digest(path) != record.get("sha256"):
        raise ValueError("frozen embedding cache differs from the approved asset manifest")
    model = manifest.get("model_source")
    if not isinstance(model, dict):
        raise ValueError("frozen embedding asset manifest lacks model provenance")
    return {
        "cache": "reused_verified_frozen_asset",
        "path": str(FROZEN_EMBEDDING_CACHE),
        "cache_sha256": record["sha256"],
        **_expected_mapping(sequence, variants),
        "checkpoint": model["esm2_checkpoint"],
        "checkpoint_commit": model["esm2_revision"],
        "provenance": "tsuboyama_stability_assets_v1",
    }


def _sidecar_metadata(path: Path, sequence: str, variants: list[Variant]) -> dict[str, Any]:
    metadata_path = _cache_metadata_path(path)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("embedding cache provenance must be a JSON object")
    expected = _expected_mapping(sequence, variants)
    if (
        payload.get("cache_sha256") != _file_digest(path)
        or payload.get("sequence_sha256") != expected["sequence_sha256"]
        or payload.get("variant_positions") != expected["variant_positions"]
        or payload.get("checkpoint") != CHECKPOINT
        or payload.get("checkpoint_commit") != CHECKPOINT_COMMIT
        or not isinstance(payload.get("checkpoint_file_sha256"), dict)
    ):
        raise ValueError("embedding cache provenance does not match the requested computation")
    return {**payload, "cache": "reused_verified_sidecar", "path": str(path)}


def load_or_extract(sequence: str, variants: list[Variant]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if EMBEDDING_CACHE.exists():
        frame = pd.read_parquet(EMBEDDING_CACHE)
        try:
            _validate_frame(frame, variants)
            metadata = _frozen_cache_metadata(EMBEDDING_CACHE, sequence, variants)
            if metadata is None:
                metadata = _sidecar_metadata(EMBEDDING_CACHE, sequence, variants)
            return frame, metadata
        except (OSError, ValueError, json.JSONDecodeError):
            # A cache without matching byte and model provenance is never reused.
            # Continue to fresh extraction, whose output receives a new sidecar.
            pass
    frame, metadata = extract_site_embeddings(sequence, variants)
    frame.to_parquet(EMBEDDING_CACHE, index=False)
    provenance = {
        **metadata,
        **_expected_mapping(sequence, variants),
        "cache_sha256": _file_digest(EMBEDDING_CACHE),
        "feature_columns": [column for column in frame.columns if column.startswith("f")],
    }
    _cache_metadata_path(EMBEDDING_CACHE).write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return frame, {**provenance, "cache": "created", "path": str(EMBEDDING_CACHE)}


def feature_lookup(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    feature_columns = [column for column in frame.columns if column.startswith("f")]
    matrix = frame[feature_columns].to_numpy(dtype=np.float32)
    return {
        str(variant_id): matrix[index]
        for index, variant_id in enumerate(frame["variant_id"])
    }


def ridge_predict(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    scaler = StandardScaler().fit(train_x)
    model = RidgeCV(alphas=np.logspace(-6, 6, 13), cv=5)
    model.fit(scaler.transform(train_x), train_y)
    return cast(np.ndarray, model.predict(scaler.transform(test_x)))


def gp_predict(
    train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    scaler = StandardScaler().fit(train_x)
    scaled_train = scaler.transform(train_x)
    scaled_test = scaler.transform(test_x)
    n_components = min(PCA_COMPONENTS, scaled_train.shape[0] - 1, scaled_train.shape[1])
    pca = PCA(n_components=n_components, random_state=SEED)
    train_reduced = pca.fit_transform(scaled_train)
    test_reduced = pca.transform(scaled_test)
    median_distance = float(np.median(pdist(train_reduced)))
    target_noise = max(float(np.var(train_y)) * 0.1, 1e-3)
    kernel = (
        ConstantKernel(max(float(np.var(train_y)), 1e-3), (1e-5, 1e3))
        * RBF(median_distance, (1e-3, 1e3))
        + WhiteKernel(target_noise, (1e-5, 1e2))
    )
    model = GaussianProcessRegressor(
        kernel=kernel,
        normalize_y=True,
        n_restarts_optimizer=0,
        random_state=SEED,
    )
    model.fit(train_reduced, train_y)
    mean, std = model.predict(test_reduced, return_std=True)
    return mean, std, {
        "pca_components": n_components,
        "pca_variance_retained": float(np.sum(pca.explained_variance_ratio_)),
        "median_pairwise_distance_reduced": median_distance,
        "kernel_after_training": str(model.kernel_),
        "hyperparameters": "optimized by training-fold marginal likelihood only",
    }


def evaluate(
    name: str,
    manifest: dict[str, Any],
    variants: dict[str, Variant],
    features: dict[str, np.ndarray],
    predictor: Any,
    include_holdout: bool,
) -> tuple[
    dict[str, list[dict[str, float | None]]],
    dict[str, float | None] | None,
    dict[str, Any],
]:
    cv: dict[str, list[dict[str, float | None]]] = {}
    diagnostics: dict[str, Any] = {}
    for scheme in ("random_5", "modulo_5", "contiguous_5"):
        fold_metrics: list[dict[str, float | None]] = []
        split = manifest["split"][scheme]["variants"]
        for fold in range(5):
            test_ids = list(split[str(fold)])
            train_ids = [
                variant_id
                for other_fold in range(5)
                if other_fold != fold
                for variant_id in split[str(other_fold)]
            ]
            train_x = np.vstack([features[variant_id] for variant_id in train_ids])
            train_y = np.array([variants[variant_id].ddg for variant_id in train_ids])
            test_x = np.vstack([features[variant_id] for variant_id in test_ids])
            test_y = np.array([variants[variant_id].ddg for variant_id in test_ids])
            prediction = predictor(train_x, train_y, test_x)
            if isinstance(prediction, tuple):
                mean, std, diagnostic = prediction
                diagnostic["prediction_sd"] = float(np.std(mean))
                diagnostic["sigma_varies"] = bool(np.std(std) > 1e-8)
                diagnostics.setdefault(scheme, []).append(diagnostic)
                prediction = mean
                diagnostics.setdefault("cv_sigma", []).append(
                    {
                        "min": float(np.min(std)),
                        "max": float(np.max(std)),
                        "mean": float(np.mean(std)),
                        "sd": float(np.std(std)),
                    }
                )
            fold_metrics.append(metric_row(test_y, prediction))
        cv[scheme] = fold_metrics

    if not include_holdout:
        return cv, None, diagnostics

    protected = {
        item["local_position"] for item in manifest["selection"]["hard_protected_residues"]
    }
    holdout_positions = set(manifest["split"]["holdout"]["positions"])
    holdout_ids = [
        variant_id
        for variant_id, variant in variants.items()
        if variant.position in holdout_positions and variant.position not in protected
    ]
    train_ids = [
        variant_id
        for variant_id, variant in variants.items()
        if variant.position not in holdout_positions
    ]
    train_x = np.vstack([features[variant_id] for variant_id in train_ids])
    train_y = np.array([variants[variant_id].ddg for variant_id in train_ids])
    test_x = np.vstack([features[variant_id] for variant_id in holdout_ids])
    test_y = np.array([variants[variant_id].ddg for variant_id in holdout_ids])
    prediction = predictor(train_x, train_y, test_x)
    if isinstance(prediction, tuple):
        mean, std, diagnostic = prediction
        diagnostic["prediction_sd"] = float(np.std(mean))
        diagnostic["sigma_varies"] = bool(np.std(std) > 1e-8)
        diagnostics["holdout"] = diagnostic
        diagnostics["holdout_std"] = {
            "min": float(np.min(std)),
            "max": float(np.max(std)),
            "mean": float(np.mean(std)),
            "sd": float(np.std(std)),
        }
        prediction = mean
    return cv, metric_row(test_y, prediction), diagnostics


def summarize_cv(
    cv: dict[str, list[dict[str, float | None]]]
) -> dict[str, dict[str, float | None]]:
    output: dict[str, dict[str, float | None]] = {}
    for scheme, rows in cv.items():
        for metric in ("spearman", "top10_recall", "ndcg", "mse"):
            values: list[float] = []
            for row in rows:
                value = row[metric]
                if value is not None:
                    values.append(value)
            key = f"{scheme}_{metric}"
            if not values:
                output[key] = {"mean": None, "sd": None}
            else:
                mean = float(np.mean(values))
                output[key] = {"mean": mean, "sd": float(np.std(values))}
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="Run the one authorized corrected-GP holdout evaluation after CV.",
    )
    args = parser.parse_args()
    manifest = load_manifest()
    sequence, rows = load_rows()
    variants = {row.variant_id: row for row in rows}
    frame, embedding_metadata = load_or_extract(sequence, rows)
    features = feature_lookup(frame)
    gp_cv, gp_holdout, gp_diagnostics = evaluate(
        "gp", manifest, variants, features, gp_predict, include_holdout=args.holdout
    )
    prior = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    output = {
        "manifest": str(MANIFEST),
        "manifest_digest": manifest["manifest_digest"],
        "embedding": embedding_metadata,
        "ridge": prior.get("ridge", {"status": "preserved from prior Gate 3 run"}),
        "gp": {
            "cv": summarize_cv(gp_cv),
            "holdout": gp_holdout,
            "diagnostics": gp_diagnostics,
        },
        "reporting": {
            "zero_shot_mse": "N/A: masked-marginal scores are not kcal/mol",
            "blosum62_mse": "N/A: substitution scores are not kcal/mol",
            "ndcg_caveat": (
                "NDCG is 0.93-0.99 for every baseline here and does not "
                "discriminate at this sample size."
            ),
            "gp_holdout_re_evaluation": (
                "authorized once after the prior GP reverted to its prior; "
                "ridge holdout was not rerun"
                if args.holdout
                else "not run because corrected GP CV was poor; authorization unused"
            ),
        },
    }
    OUTPUT.write_text(json.dumps(output, indent=2, allow_nan=False))
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
