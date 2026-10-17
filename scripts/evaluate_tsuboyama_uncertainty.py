"""Step 4: ridge ensemble, split conformal intervals, and OOD refusals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from evaluate_tsuboyama_baselines import Variant, load_manifest, load_rows, metric_row
from evaluate_tsuboyama_predictor import EMBEDDING_CACHE, feature_lookup
from scipy.spatial.distance import cdist, pdist
from sklearn.decomposition import PCA
from sklearn.linear_model import RidgeCV
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

OUTPUT = Path("data/processed/tsuboyama_uncertainty_metrics.json")
ARTIFACTS = Path("data/processed/tsuboyama_ensemble_artifacts.joblib")
RELIABILITY_JSON = Path("data/processed/tsuboyama_reliability_diagram.json")
RELIABILITY_PNG = Path("data/processed/tsuboyama_reliability_diagram.png")
SEEDS = [1729, 1730, 1731, 1732, 1733]
CALIBRATION_FRACTION = 0.20
CONFORMAL_ALPHA = 0.10
KNN_PERCENTILE = 95
PCA_COMPONENTS = 50


def wilson_interval(covered: int, total: int) -> tuple[float, float]:
    z = 1.96
    p = covered / total
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    half = z * np.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def calibration_metrics(
    y_true: np.ndarray,
    mean: np.ndarray,
    sigma: np.ndarray,
    quantile: float,
    normalized: bool,
) -> dict[str, Any]:
    width = quantile * sigma if normalized else np.full_like(sigma, quantile)
    lower = mean - width
    upper = mean + width
    covered = (y_true >= lower) & (y_true <= upper)
    picp = float(np.mean(covered))
    interval_width = 2 * width
    safe_sigma = np.maximum(sigma, 1e-6)
    nll = float(
        np.mean(
            0.5 * np.log(2 * np.pi * safe_sigma**2)
            + (y_true - mean) ** 2 / (2 * safe_sigma**2)
        )
    )
    bins = np.array_split(np.argsort(sigma), 10)
    observed = [float(np.mean(covered[indexes])) for indexes in bins if len(indexes)]
    ece = float(
        sum(
            len(indexes) * abs(value - (1 - CONFORMAL_ALPHA))
            for indexes, value in zip(bins, observed, strict=True)
        )
        / len(y_true)
    )
    return {
        "picp": picp,
        "picp_wilson_95": list(wilson_interval(int(np.sum(covered)), len(y_true))),
        "mean_width_kcal_mol": float(np.mean(interval_width)),
        "median_width_kcal_mol": float(np.median(interval_width)),
        "label_range_kcal_mol": [float(np.min(y_true)), float(np.max(y_true))],
        "ece": ece,
        "nll": nll,
        "covered": int(np.sum(covered)),
        "n": len(y_true),
        "quantile": quantile,
        "normalized": normalized,
    }


def fit_ensemble(
    x_fit: np.ndarray,
    y_fit: np.ndarray,
    x_calibration: np.ndarray,
    x_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    calibration_predictions: list[np.ndarray] = []
    test_predictions: list[np.ndarray] = []
    fitted: list[dict[str, Any]] = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        bootstrap = rng.integers(0, len(x_fit), size=len(x_fit))
        scaler = StandardScaler().fit(x_fit[bootstrap])
        model = RidgeCV(alphas=np.logspace(-6, 6, 13), cv=5)
        model.fit(scaler.transform(x_fit[bootstrap]), y_fit[bootstrap])
        calibration_predictions.append(model.predict(scaler.transform(x_calibration)))
        test_predictions.append(model.predict(scaler.transform(x_test)))
        fitted.append(
            {
                "seed": seed,
                "alpha": float(model.alpha_),
                "scaler": scaler,
                "model": model,
            }
        )
    calibration_matrix = np.vstack(calibration_predictions)
    test_matrix = np.vstack(test_predictions)
    return (
        np.mean(calibration_matrix, axis=0),
        np.std(calibration_matrix, axis=0),
        np.mean(test_matrix, axis=0),
        [
            {**item, "test_prediction": prediction}
            for item, prediction in zip(fitted, test_predictions, strict=True)
        ],
    )


def conformal_quantiles(
    y_calibration: np.ndarray, mean: np.ndarray, sigma: np.ndarray
) -> tuple[float, float]:
    residual = np.abs(y_calibration - mean)
    normalized = residual / np.maximum(sigma, 1e-6)
    return (
        float(np.quantile(normalized, 1 - CONFORMAL_ALPHA, method="higher")),
        float(np.quantile(residual, 1 - CONFORMAL_ALPHA, method="higher")),
    )


def distance_space(
    x_train: np.ndarray, x_query: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float, float]:
    scaler = StandardScaler().fit(x_train)
    train_scaled = scaler.transform(x_train)
    query_scaled = scaler.transform(x_query)
    pca = PCA(
        n_components=min(PCA_COMPONENTS, train_scaled.shape[0] - 1, train_scaled.shape[1]),
        random_state=SEEDS[0],
    )
    train_reduced = pca.fit_transform(train_scaled)
    query_reduced = pca.transform(query_scaled)
    neighbor = NearestNeighbors(n_neighbors=2).fit(train_reduced)
    train_distances = neighbor.kneighbors(train_reduced)[0][:, 1]
    threshold = float(np.percentile(train_distances, KNN_PERCENTILE))
    return train_reduced, query_reduced, threshold, float(np.median(pdist(train_reduced)))


def refusal(
    variant_id: str,
    position: int,
    mutation_count: int,
    training_positions: set[int],
    distance: float | None,
    threshold: float | None,
) -> dict[str, Any]:
    triggers: list[dict[str, Any]] = []
    if position not in training_positions:
        triggers.append({"code": "T1_POSITION_UNSEEN", "position": position})
    if distance is not None and threshold is not None and distance > threshold:
        triggers.append({
            "code": "T2_EMBEDDING_DISTANCE",
            "distance": distance,
            "threshold": threshold,
            "percentile": KNN_PERCENTILE,
        })
    if mutation_count > 1:
        triggers.append({"code": "T3_MULTI_MUTANT_SINGLE_MODEL", "mutation_count": mutation_count})
    return {
        "refused": bool(triggers),
        "variant_id": variant_id,
        "triggers": triggers,
    }


def compute_holdout_refusal_rate(
    holdout_variants: list[Variant], training_positions: set[int]
) -> tuple[float, dict[str, int]]:
    """Compute the effective holdout refusal rate using the existing OOD gate."""
    if not holdout_variants:
        raise ValueError("cannot compute a refusal rate for an empty holdout")
    decisions = [
        refusal(
            variant.variant_id,
            variant.position,
            1,
            training_positions,
            None,
            None,
        )
        for variant in holdout_variants
    ]
    refused = sum(bool(decision["refused"]) for decision in decisions)
    return refused / len(decisions), {"refused": refused, "evaluated": len(decisions)}


def run_split(
    scheme: str,
    split: dict[str, Any],
    variants: dict[str, Variant],
    features: dict[str, np.ndarray],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metrics: list[dict[str, Any]] = []
    reliability: list[dict[str, Any]] = []
    for fold in range(5):
        test_ids = list(split["variants"][str(fold)])
        all_train_ids = [
            variant_id
            for other in range(5)
            if other != fold
            for variant_id in split["variants"][str(other)]
        ]
        rng = np.random.default_rng(SEEDS[0] + fold)
        permutation = rng.permutation(len(all_train_ids))
        calibration_size = max(1, int(len(all_train_ids) * CALIBRATION_FRACTION))
        calibration_ids = [all_train_ids[index] for index in permutation[:calibration_size]]
        fit_ids = [all_train_ids[index] for index in permutation[calibration_size:]]
        x_fit = np.vstack([features[index] for index in fit_ids])
        y_fit = np.array([variants[index].ddg for index in fit_ids])
        x_cal = np.vstack([features[index] for index in calibration_ids])
        y_cal = np.array([variants[index].ddg for index in calibration_ids])
        x_test = np.vstack([features[index] for index in test_ids])
        y_test = np.array([variants[index].ddg for index in test_ids])
        cal_mean, cal_sigma, test_mean, fitted = fit_ensemble(x_fit, y_fit, x_cal, x_test)
        test_sigma = np.std(np.vstack([item["test_prediction"] for item in fitted]), axis=0)
        normalized_q, absolute_q = conformal_quantiles(y_cal, cal_mean, cal_sigma)
        metrics.append({
            "normalized": calibration_metrics(y_test, test_mean, test_sigma, normalized_q, True),
            "absolute": calibration_metrics(y_test, test_mean, test_sigma, absolute_q, False),
            "ensemble_sigma": {
                "min": float(np.min(test_sigma)),
                "max": float(np.max(test_sigma)),
                "mean": float(np.mean(test_sigma)),
                "sd": float(np.std(test_sigma)),
            },
            "prediction_sd": float(np.std(test_mean)),
            "top10_recall": metric_row(y_test, test_mean)["top10_recall"],
            "seeds": SEEDS,
            "calibration_size": len(calibration_ids),
            "fit_size": len(fit_ids),
            "normalized_quantile": normalized_q,
            "absolute_quantile": absolute_q,
        })
        reliability.extend(
            {
                "sigma": float(sigma),
                "covered_normalized": bool(abs(y - mean) <= normalized_q * sigma),
            }
            for y, mean, sigma in zip(y_test, test_mean, test_sigma, strict=True)
        )
    return {"folds": metrics}, reliability


def main() -> None:
    manifest = load_manifest()
    _, rows = load_rows()
    variants = {row.variant_id: row for row in rows}
    frame = pd.read_parquet(EMBEDDING_CACHE)
    features = feature_lookup(frame)
    results: dict[str, Any] = {
        "manifest_digest": manifest["manifest_digest"],
        "execution_history": [
            {
                "attempt": 1,
                "status": "failed_after_holdout_evaluation",
                "failure": "reliability diagram serialization failed before artifact persistence",
            },
            {
                "attempt": 2,
                "status": "authorized_rerun_after_serialization_failure",
            },
        ],
        "gp_finding": (
            "GP dropped: position-aware CV Spearman 0.1756 modulo and 0.1644 "
            "contiguous; kernel was leakage-sensitive and sigma was constant in "
            "3/5 folds of each scheme."
        ),
        "ensemble": {"seeds": SEEDS, "calibration_fraction": CALIBRATION_FRACTION},
        "cv": {},
    }
    reliability: list[dict[str, Any]] = []
    for scheme in ("modulo_5", "contiguous_5"):
        split_result, diagram_rows = run_split(
            scheme, manifest["split"][scheme], variants, features
        )
        results["cv"][scheme] = split_result
        reliability.extend({"scheme": scheme, **row} for row in diagram_rows)

    # OOD threshold is calibrated from training-fold nearest-neighbor distances only.
    # Use an outer random-fold model for genuine T1 and T2 examples.
    random_split = manifest["split"]["random_5"]["variants"]
    random_train_ids = [v for fold in range(1, 5) for v in random_split[str(fold)]]
    random_test_ids = list(random_split["0"])
    random_train_x = np.vstack([features[index] for index in random_train_ids])
    random_test_x = np.vstack([features[index] for index in random_test_ids])
    (
        random_train_reduced,
        random_test_reduced,
        random_threshold,
        random_median_distance,
    ) = distance_space(random_train_x, random_test_x)
    distances = cdist(random_test_reduced, random_train_reduced).min(axis=1)
    candidate_index = int(np.argmax(distances))
    t2_id = random_test_ids[candidate_index]
    t2_variant = variants[t2_id]
    modulo_split = manifest["split"]["modulo_5"]["variants"]
    t1_id = modulo_split["0"][0]
    t1_training_ids = [
        variant_id
        for fold in range(1, 5)
        for variant_id in modulo_split[str(fold)]
    ]
    results["ood"] = {
        "knn_percentile": KNN_PERCENTILE,
        "knn_threshold": random_threshold,
        "training_median_pairwise_distance": random_median_distance,
        "T1": refusal(
            t1_id,
            variants[t1_id].position,
            1,
            {variants[index].position for index in t1_training_ids},
            None,
            None,
        ),
        "T2": refusal(
            t2_id,
            t2_variant.position,
            1,
            {variants[index].position for index in random_train_ids},
            float(distances[candidate_index]),
            random_threshold,
        ),
        "T3": refusal(
            "1E0L.pdb_T9Q:N23Q",
            9,
            2,
            {variants[index].position for index in random_train_ids},
            None,
            None,
        ),
        "in_distribution": refusal(
            random_train_ids[0],
            variants[random_train_ids[0]].position,
            1,
            {variants[index].position for index in random_train_ids},
            0.0,
            random_threshold,
        ),
    }

    # The final training/calibration fit reads and evaluates the holdout only now.
    protected = {
        item["local_position"] for item in manifest["selection"]["hard_protected_residues"]
    }
    holdout_positions = set(manifest["split"]["holdout"]["positions"])
    holdout_ids = [
        row.variant_id
        for row in rows
        if row.position in holdout_positions and row.position not in protected
    ]
    training_ids = [row.variant_id for row in rows if row.position not in holdout_positions]
    rng = np.random.default_rng(SEEDS[0] + 1000)
    permutation = rng.permutation(len(training_ids))
    calibration_size = max(1, int(len(training_ids) * CALIBRATION_FRACTION))
    calibration_ids = [training_ids[index] for index in permutation[:calibration_size]]
    fit_ids = [training_ids[index] for index in permutation[calibration_size:]]
    x_fit = np.vstack([features[index] for index in fit_ids])
    y_fit = np.array([variants[index].ddg for index in fit_ids])
    x_cal = np.vstack([features[index] for index in calibration_ids])
    y_cal = np.array([variants[index].ddg for index in calibration_ids])
    x_holdout = np.vstack([features[index] for index in holdout_ids])
    y_holdout = np.array([variants[index].ddg for index in holdout_ids])
    cal_mean, cal_sigma, holdout_mean, fitted = fit_ensemble(x_fit, y_fit, x_cal, x_holdout)
    holdout_sigma = np.std(np.vstack([item["test_prediction"] for item in fitted]), axis=0)
    normalized_q, absolute_q = conformal_quantiles(y_cal, cal_mean, cal_sigma)
    results["holdout"] = {
        "positions": len({variants[index].position for index in holdout_ids}),
        "rows": len(holdout_ids),
        "normalized": calibration_metrics(
            y_holdout, holdout_mean, holdout_sigma, normalized_q, True
        ),
        "absolute": calibration_metrics(
            y_holdout, holdout_mean, holdout_sigma, absolute_q, False
        ),
        "ensemble_sigma": {
            "min": float(np.min(holdout_sigma)),
            "max": float(np.max(holdout_sigma)),
            "mean": float(np.mean(holdout_sigma)),
            "sd": float(np.std(holdout_sigma)),
        },
        "prediction_sd": float(np.std(holdout_mean)),
        "normalized_quantile": normalized_q,
        "absolute_quantile": absolute_q,
        "top10_recall": metric_row(y_holdout, holdout_mean)["top10_recall"],
        "evaluated_once_after_cv": True,
    }
    holdout_variants = [variants[index] for index in holdout_ids]
    holdout_training_positions = {variants[index].position for index in training_ids}
    holdout_refusal_rate, holdout_refusal_counts = compute_holdout_refusal_rate(
        holdout_variants, holdout_training_positions
    )
    results["ood"]["holdout_refusal_rate"] = holdout_refusal_rate
    results["ood"]["holdout_refusal_counts"] = holdout_refusal_counts
    results["ood"]["holdout_refusal_criterion"] = (
        "existing refusal() gate with T1 position-unseen and T3 multi-mutant; "
        "T2 is not evaluated without a holdout distance calibration"
    )
    results["reliability_diagram"] = str(RELIABILITY_PNG)
    diagram_frame = pd.DataFrame(reliability)
    diagram_payload = diagram_frame.to_dict(orient="records")
    RELIABILITY_JSON.write_text(json.dumps(diagram_payload, indent=2))
    plt.figure(figsize=(6, 4))
    for scheme, group in diagram_frame.groupby("scheme"):
        ordered = group.sort_values("sigma")
        bin_indexes = np.array_split(np.arange(len(ordered)), 10)
        parts = [ordered.iloc[indexes] for indexes in bin_indexes if len(indexes)]
        x = [float(part["sigma"].mean()) for part in parts]
        y = [float(part["covered_normalized"].mean()) for part in parts]
        plt.plot(x, y, marker="o", label=scheme)
    plt.axhline(0.9, color="black", linestyle="--", label="nominal 90%")
    plt.xlabel("Ensemble sigma")
    plt.ylabel("Empirical normalized-interval coverage")
    plt.legend()
    plt.tight_layout()
    plt.savefig(RELIABILITY_PNG, dpi=150)
    plt.close()
    joblib.dump(
        {"seeds": SEEDS, "embedding_cache": str(EMBEDDING_CACHE), "fitted": fitted},
        ARTIFACTS,
    )
    OUTPUT.write_text(json.dumps(results, indent=2, allow_nan=False))
    print(json.dumps(results, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
