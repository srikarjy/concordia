"""Run the frozen ESM-2 site-embedding predictor for Gate 3."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import torch
from evaluate_tsuboyama_baselines import (
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
from transformers import AutoTokenizer, EsmModel

EMBEDDING_CACHE = Path("data/processed/tsuboyama_esm2_site_embeddings.parquet")
OUTPUT = Path("data/processed/tsuboyama_predictor_metrics.json")
CHECKPOINT_COMMIT = "08e4846e537177426273712802403f7ba8261b6c"
SEED = 1729
BATCH_SIZE = 8
PCA_COMPONENTS = 50


def mutate(sequence: str, position: int, mutant: str) -> str:
    return sequence[: position - 1] + mutant + sequence[position:]


def extract_site_embeddings(
    sequence: str, variants: list[Variant]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)  # type: ignore[no-untyped-call]
    model = EsmModel.from_pretrained(CHECKPOINT).eval()
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


def load_or_extract(sequence: str, variants: list[Variant]) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected_ids = {row.variant_id for row in variants}
    if EMBEDDING_CACHE.exists():
        frame = pd.read_parquet(EMBEDDING_CACHE)
        if set(frame["variant_id"]) == expected_ids:
            metadata = {
                "cache": "reused",
                "path": str(EMBEDDING_CACHE),
                "checkpoint": CHECKPOINT,
                "checkpoint_commit": CHECKPOINT_COMMIT,
            }
            return frame, metadata
    frame, metadata = extract_site_embeddings(sequence, variants)
    frame.to_parquet(EMBEDDING_CACHE, index=False)
    metadata["cache"] = "created"
    metadata["path"] = str(EMBEDDING_CACHE)
    return frame, metadata


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
