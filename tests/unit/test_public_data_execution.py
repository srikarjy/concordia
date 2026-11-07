"""Check the published real-data result independently of the HTTP runner."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge


def test_published_model_and_metrics_reproduce_from_training_rows_only() -> None:
    root = Path(__file__).parents[2] / "frontend/public/public-data-review"
    report = json.loads((root / "execution.json").read_text())
    with (root / "measured-dataset.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]
    assert len(rows) == len({r["sequence"] for r in rows}) == 930
    assert {r["position"] for r in train}.isdisjoint({r["position"] for r in test})
    assert [r["candidate_id"] for r in train] == report["training"]["train_ids"]
    assert [r["candidate_id"] for r in test] == report["training"]["test_ids"]
    aa = report["training"]["feature_order"]
    x_train = np.array([[r["sequence"].count(a) for a in aa] for r in train])
    x_test = np.array([[r["sequence"].count(a) for a in aa] for r in test])
    y_train = np.array([float(r["deltaG_kcal_mol"]) for r in train])
    y_test = np.array([float(r["deltaG_kcal_mol"]) for r in test])
    fitted = Ridge(alpha=1.0, solver="svd").fit(x_train, y_train)
    assert fitted.coef_ == pytest.approx(report["training"]["coefficients"], abs=1e-10)
    predictions = fitted.predict(x_test)
    assert np.sqrt(np.mean((predictions - y_test) ** 2)) == pytest.approx(report["ridge_rmse"])
    assert np.sqrt(np.mean((y_train.mean() - y_test) ** 2)) == pytest.approx(
        report["mean_baseline_rmse"]
    )
    assert spearmanr(predictions, y_test).statistic == pytest.approx(report["ridge_spearman"])
    assert report["scientific_use_allowed"] is False
