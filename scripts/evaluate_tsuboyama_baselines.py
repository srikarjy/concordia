"""Evaluate the frozen Tsuboyama baselines without changing the manifest."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from Bio.Align import substitution_matrices
from scipy.stats import spearmanr
from sklearn.linear_model import RidgeCV
from sklearn.metrics import ndcg_score

MANIFEST = Path("data/manifests/tsuboyama_rule2_manifest_v3.json")
TABLE = Path("data/processed/tsuboyama_v2_230420_normalized.csv")
ESM_CACHE = Path("data/processed/tsuboyama_esm2_zero_shot.json")
OUTPUT = Path("data/processed/tsuboyama_baseline_metrics.json")
CHECKPOINT = "facebook/esm2_t33_650M_UR50D"
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


@dataclass(frozen=True)
class Variant:
    variant_id: str
    position: int
    mutant: str
    ddg: float


def load_rows() -> tuple[str, list[Variant]]:
    rows: list[Variant] = []
    wild_type = ""
    with TABLE.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["domain_id"] != "1IGV.pdb":
                continue
            if raw["is_wild_type"] == "True":
                wild_type = raw["wild_type_sequence"]
                continue
            mutation = raw["mutation"]
            rows.append(
                Variant(
                    variant_id=raw["variant_id"],
                    position=int(raw["position"]),
                    mutant=mutation[-1],
                    ddg=float(raw["ddg_kcal_higher_is_more_stable"]),
                )
            )
    if not wild_type or len(rows) != 1406:
        raise ValueError("unexpected selected-domain row count or missing wild type")
    return wild_type, rows


def load_manifest() -> dict[str, Any]:
    manifest = cast(dict[str, Any], json.loads(MANIFEST.read_text()))
    expected = "ecaa921917627178638397955def230d9bc1563cc4122ac27a099e6f618f25d7"
    if manifest["manifest_digest"] != expected:
        raise ValueError("manifest digest does not match the requested v3 manifest")
    holdout = set(manifest["split"]["holdout"]["positions"])
    for scheme in ("random_5", "modulo_5", "contiguous_5"):
        split = manifest["split"][scheme]
        fold_positions = [set(values) for values in split["positions"].values()]
        fold_variants = [set(values) for values in split["variants"].values()]
        for fold in range(5):
            training_positions = set().union(
                *(fold_positions[index] for index in range(5) if index != fold)
            )
            if holdout & training_positions:
                raise ValueError(f"holdout overlaps {scheme} training positions")
        if any("1IGV.pdb" in values for values in fold_variants):
            raise ValueError(f"wild type appears in {scheme}")
        distinct = [len(values) for values in fold_positions]
        if scheme == "random_5" and min(distinct) <= 60:
            raise ValueError("random folds do not span >60 positions")
        if scheme != "random_5" and not all(12 <= count <= 14 for count in distinct):
            raise ValueError(f"unexpected position span for {scheme}: {distinct}")
    return manifest


def metric_row(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    rho = spearmanr(y_true, y_pred).statistic
    if not np.isfinite(rho):
        rho = None
    top_n = max(1, int(np.ceil(len(y_true) * 0.10)))
    true_top = set(np.argsort(y_true)[-top_n:])
    pred_top = set(np.argsort(y_pred)[-top_n:])
    recall = len(true_top & pred_top) / len(true_top)
    relevance = y_true - np.min(y_true)
    ndcg = float(ndcg_score(relevance.reshape(1, -1), y_pred.reshape(1, -1)))
    return {
        "spearman": None if rho is None else float(rho),
        "top10_recall": float(recall),
        "ndcg": ndcg,
        "mse": float(np.mean((y_true - y_pred) ** 2)),
    }


def one_hot(variants: list[Variant]) -> np.ndarray:
    features = np.zeros((len(variants), 74 + len(AMINO_ACIDS)), dtype=np.float32)
    for row, variant in enumerate(variants):
        features[row, variant.position - 1] = 1
        features[row, 74 + AMINO_ACIDS.index(variant.mutant)] = 1
    return features


def fit_predict_one_hot(train: list[Variant], test: list[Variant]) -> np.ndarray:
    model = RidgeCV(alphas=np.logspace(-6, 6, 13), cv=5)
    model.fit(one_hot(train), np.array([row.ddg for row in train]))
    return cast(np.ndarray, model.predict(one_hot(test)))


def get_esm_scores(
    sequence: str, variants: list[Variant]
) -> tuple[dict[str, float], dict[str, Any]]:
    if ESM_CACHE.exists():
        cached = json.loads(ESM_CACHE.read_text())
        if (
            cached.get("sequence") == sequence
            and cached.get("metadata", {}).get("checkpoint") == CHECKPOINT
        ):
            return cached["scores"], cached["metadata"]

    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    import torch
    from huggingface_hub import HfApi
    from transformers import AutoTokenizer, EsmForMaskedLM

    info = HfApi().model_info(CHECKPOINT)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)  # type: ignore[no-untyped-call]
    model = EsmForMaskedLM.from_pretrained(CHECKPOINT).eval()
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model.to(device)
    encoded = tokenizer(sequence, return_tensors="pt")
    input_ids = encoded["input_ids"].to(device)
    mask_id = tokenizer.mask_token_id
    wild_type_scores: dict[str, float] = {}
    cpu_diffs: list[float] = []
    with torch.no_grad():
        for index in range(len(sequence)):
            masked = input_ids.clone()
            masked[0, index + 1] = mask_id
            logits = model(masked).logits[0, index + 1]
            log_probs = torch.log_softmax(logits, dim=-1)
            wild_id = tokenizer.convert_tokens_to_ids(sequence[index])
            for mutant in AMINO_ACIDS:
                mutant_id = tokenizer.convert_tokens_to_ids(mutant)
                variant_id = f"1IGV.pdb_{sequence[index]}{index + 1}{mutant}"
                wild_type_scores[variant_id] = float(log_probs[mutant_id] - log_probs[wild_id])
            if index < 5:
                cpu_input = masked.detach().cpu()
                cpu_logits = model.to("cpu")(cpu_input).logits[0, index + 1]
                cpu_log_probs = torch.log_softmax(cpu_logits, dim=-1)
                cpu_diffs.append(
                    float(torch.max(torch.abs(log_probs.detach().cpu() - cpu_log_probs)))
                )
                model.to(device)
    metadata = {
        "checkpoint": CHECKPOINT,
        "checkpoint_commit": info.sha,
        "device": str(device),
        "mps_available": bool(torch.backends.mps.is_available()),
        "mps_cpu_max_abs_diff_first_5": max(cpu_diffs, default=0.0),
        "score_definition": (
            "log P(mutant | masked wild type) - "
            "log P(wild type | masked wild type)"
        ),
    }
    ESM_CACHE.write_text(
        json.dumps(
            {"sequence": sequence, "scores": wild_type_scores, "metadata": metadata},
            indent=2,
        )
    )
    return wild_type_scores, metadata


def baseline_predictions(
    name: str, train: list[Variant], test: list[Variant], esm: dict[str, float]
) -> np.ndarray:
    if name == "training_mean":
        return np.full(len(test), np.mean([row.ddg for row in train]))
    if name == "one_hot_ridge":
        return fit_predict_one_hot(train, test)
    if name == "esm2_zero_shot":
        return np.array([esm[row.variant_id] for row in test])
    raise ValueError(name)


def blosum_predictions(sequence: str, variants: list[Variant]) -> np.ndarray:
    matrix = substitution_matrices.load("BLOSUM62")  # type: ignore[no-untyped-call]
    return np.array([float(matrix[sequence[row.position - 1], row.mutant]) for row in variants])


def main() -> None:
    manifest = load_manifest()
    sequence, rows = load_rows()
    by_id = {row.variant_id: row for row in rows}
    protected = {
        item["local_position"] for item in manifest["selection"]["hard_protected_residues"]
    }
    holdout_positions = set(manifest["split"]["holdout"]["positions"])
    holdout = [
        row
        for row in rows
        if row.position in holdout_positions and row.position not in protected
    ]
    esm, esm_metadata = get_esm_scores(sequence, rows)
    all_results: dict[str, Any] = {
        "manifest_digest": manifest["manifest_digest"],
        "cv": {},
        "holdout": {},
        "esm": esm_metadata,
    }
    baselines = ["training_mean", "one_hot_ridge", "esm2_zero_shot", "blosum62"]
    for scheme in ("random_5", "modulo_5", "contiguous_5"):
        split = manifest["split"][scheme]["variants"]
        fold_results: dict[str, list[dict[str, float | None]]] = {name: [] for name in baselines}
        for fold in range(5):
            test = [by_id[variant_id] for variant_id in split[str(fold)]]
            train = [
                by_id[variant_id]
                for other_fold in range(5)
                if other_fold != fold
                for variant_id in split[str(other_fold)]
            ]
            y_true = np.array([row.ddg for row in test])
            for name in baselines:
                if name == "blosum62":
                    prediction = blosum_predictions(sequence, test)
                else:
                    prediction = baseline_predictions(name, train, test, esm)
                fold_results[name].append(metric_row(y_true, prediction))
        all_results["cv"][scheme] = fold_results

    # The frozen holdout is evaluated only after all CV results have been finalized.
    train = [row for row in rows if row.position not in holdout_positions]
    y_true = np.array([row.ddg for row in holdout])
    for name in baselines:
        prediction = (
            blosum_predictions(sequence, holdout)
            if name == "blosum62"
            else baseline_predictions(name, train, holdout, esm)
        )
        all_results["holdout"][name] = metric_row(y_true, prediction)
    OUTPUT.write_text(json.dumps(all_results, indent=2, allow_nan=False))
    print(json.dumps(all_results, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
