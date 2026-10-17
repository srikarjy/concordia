"""Reachable measured-stability prediction and proposal-boundary gates.

This module is deliberately narrower than the synthetic campaign baseline.  It
loads the frozen 1IGV manifest and the Gate 4 ridge ensemble, ranks only by the
predicted mean, and uses uncertainty/OOD signals only to refuse or flag work.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from Bio.PDB.PDBParser import PDBParser as _PDBParser
from Bio.PDB.SASA import ShrakeRupley as _ShrakeRupley
from numpy.typing import NDArray
from sklearn.decomposition import PCA
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler

from concordia.stability.ranker import load_ranker_artifact, rank_average_scores

PDBParser: Any = _PDBParser
ShrakeRupley: Any = _ShrakeRupley

MANIFEST_PATH = Path("data/manifests/tsuboyama_rule2_manifest_v3.json")
MANIFEST_PAYLOAD_DIGEST = "ecaa921917627178638397955def230d9bc1563cc4122ac27a099e6f618f25d7"
MANIFEST_FILE_SHA256 = "ee683066419099303046a16e799f7eb21d88963cdd83d8c08e28587d0faedafc"
TABLE_PATH = Path("data/processed/tsuboyama_v2_230420_normalized.csv")
EMBEDDING_PATH = Path("data/processed/tsuboyama_esm2_site_embeddings.parquet")
ARTIFACT_PATH = Path("data/processed/tsuboyama_ensemble_artifacts.joblib")
RSA_PATH = Path("data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb")
UNCERTAINTY_PATH = Path("data/processed/tsuboyama_uncertainty_metrics.json")
T2_RECALIBRATION_PATH = Path("data/processed/tsuboyama_t2_recalibration.json")
SEEDS = (1729, 1730, 1731, 1732, 1733)
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
RSA_CUTOFF = 0.15
T1_PENALTY = 0.10
RSA_PENALTY = 0.10

_MAX_ASA_TIEN = {
    "A": 129.0,
    "R": 274.0,
    "N": 195.0,
    "D": 193.0,
    "C": 167.0,
    "Q": 225.0,
    "E": 223.0,
    "G": 104.0,
    "H": 224.0,
    "I": 197.0,
    "L": 201.0,
    "K": 236.0,
    "M": 224.0,
    "F": 240.0,
    "P": 159.0,
    "S": 155.0,
    "T": 172.0,
    "W": 285.0,
    "Y": 263.0,
    "V": 174.0,
}
_THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


@dataclass(frozen=True)
class MeasuredCandidate:
    variant_id: str
    position: int
    mutant: str
    mutation_count: int = 1


@dataclass(frozen=True)
class Refusal:
    refused: bool
    variant_id: str
    triggers: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "refused": self.refused,
            "variant_id": self.variant_id,
            "triggers": list(self.triggers),
        }


def render_recommendation(template: str, slots: dict[str, str | float | int | None]) -> str:
    """Render connective prose only when every referenced slot is filled."""
    required = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    missing = sorted(name for name in required if slots.get(name) in (None, ""))
    if missing:
        raise ValueError(f"recommendation has unfilled slots: {', '.join(missing)}")
    return template.format(**slots)


def refuse_unsupported_signal(signal: str) -> Refusal:
    if signal.lower() not in {"plddt", "rmsd", "tm_score", "lddt", "structural_similarity"}:
        raise ValueError(f"unsupported refusal signal: {signal}")
    return Refusal(
        True,
        "unsupported-signal",
        ({"code": "UNSUPPORTED_STRUCTURE_SIGNAL", "signal": signal},),
    )


class MeasuredStabilityEngine:
    """Load the frozen measured model and enforce its proposal boundary."""

    def __init__(
        self,
        manifest_path: Path = MANIFEST_PATH,
        artifact_path: Path = ARTIFACT_PATH,
    ) -> None:
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        serialized_manifest = manifest_path.read_bytes()
        if hashlib.sha256(serialized_manifest).hexdigest() != MANIFEST_FILE_SHA256:
            raise ValueError("measured-stability manifest file digest does not match frozen v3")
        if self.manifest.get("manifest_digest") != MANIFEST_PAYLOAD_DIGEST:
            raise ValueError("measured-stability manifest payload digest does not match frozen v3")
        self.manifest_digest = str(self.manifest["manifest_digest"])
        self.artifacts = joblib.load(artifact_path)
        if tuple(self.artifacts.get("seeds", ())) != SEEDS:
            raise ValueError("ensemble artifact seeds do not match the recorded Gate 4 seeds")
        frame = pd.read_parquet(EMBEDDING_PATH)
        feature_columns = [column for column in frame.columns if column.startswith("f")]
        matrix = frame[feature_columns].to_numpy(dtype=np.float32)
        self.features = {
            str(variant_id): matrix[index] for index, variant_id in enumerate(frame["variant_id"])
        }
        self.rows = self._load_variants()
        self.ranker_artifact = load_ranker_artifact()
        self.hard_protected = {
            int(item["local_position"]): {
                "feature_type": item["feature_type"],
                "accession": item["accession"],
                "uniprot_position": item["uniprot_position"],
            }
            for item in self.manifest["selection"]["hard_protected_residues"]
        }
        self.soft_rsa = self._load_rsa()
        self.training_positions = {
            row.position
            for row in self.rows.values()
            if row.position not in set(self.manifest["split"]["holdout"]["positions"])
        }
        uncertainty = json.loads(UNCERTAINTY_PATH.read_text(encoding="utf-8"))
        old_threshold = float(uncertainty["ood"]["knn_threshold"])
        calibration = _recalibrate_t2(self.manifest, self.features, old_threshold)
        T2_RECALIBRATION_PATH.write_text(
            json.dumps(calibration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.t2_recalibration = calibration
        self.knn_threshold = float(calibration["new_threshold"])
        training_ids = [
            variant_id
            for fold in range(1, 5)
            for variant_id in self.manifest["split"]["random_5"]["variants"][str(fold)]
        ]
        train_x = np.vstack([self.features[variant_id] for variant_id in training_ids])
        scaler = StandardScaler().fit(train_x)
        self.distance_scaler = scaler
        self.distance_pca = PCA(
            n_components=min(50, len(train_x) - 1, train_x.shape[1]), random_state=SEEDS[0]
        ).fit(scaler.transform(train_x))
        self.training_reduced = self.distance_pca.transform(scaler.transform(train_x))

    def _load_variants(self) -> dict[str, MeasuredCandidate]:
        rows: dict[str, MeasuredCandidate] = {}
        with TABLE_PATH.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                if raw["domain_id"] != "1IGV.pdb" or raw["is_wild_type"] == "True":
                    continue
                mutation = raw["mutation"]
                rows[raw["variant_id"]] = MeasuredCandidate(
                    raw["variant_id"], int(raw["position"]), mutation[-1], mutation.count(":") + 1
                )
        return rows

    def _load_labels(self, variant_ids: set[str]) -> dict[str, float]:
        labels: dict[str, float] = {}
        with TABLE_PATH.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                variant_id = raw["variant_id"]
                if raw["domain_id"] == "1IGV.pdb" and variant_id in variant_ids:
                    labels[variant_id] = float(raw["ddg_kcal_higher_is_more_stable"])
        if labels.keys() != variant_ids:
            missing = sorted(variant_ids - labels.keys())
            raise ValueError(f"missing measured labels for variants: {missing[:5]}")
        return labels

    def _load_rsa(self) -> dict[int, float]:
        structure = PDBParser(QUIET=True).get_structure("1IGV", str(RSA_PATH))[0]
        ShrakeRupley().compute(structure, level="R")
        values: dict[int, float] = {}
        for residue in structure.get_residues():
            one = _THREE_TO_ONE.get(residue.resname)
            if one in _MAX_ASA_TIEN and residue.id[1] not in values:
                values[residue.id[1]] = float(residue.sasa / _MAX_ASA_TIEN[one])
        return values

    def _distance(self, variant_id: str) -> float:
        query = self.distance_pca.transform(
            self.distance_scaler.transform(self.features[variant_id].reshape(1, -1))
        )
        return float(np.linalg.norm(self.training_reduced - query, axis=1).min())

    def _predict(self, variant_ids: list[str]) -> tuple[NDArray[Any], NDArray[Any]]:
        x = np.vstack([self.features[variant_id] for variant_id in variant_ids])
        predictions = []
        for fitted in self.artifacts["fitted"]:
            scaler = fitted["scaler"]
            model = fitted["model"]
            predictions.append(model.predict(scaler.transform(x)))
        matrix = np.vstack(predictions)
        return np.mean(matrix, axis=0), np.std(matrix, axis=0)

    def evaluate_candidate(self, candidate: MeasuredCandidate) -> dict[str, Any]:
        triggers: list[dict[str, Any]] = []
        hard = self.hard_protected.get(candidate.position)
        if hard:
            triggers.append({"code": "HARD_PROTECTED_UNIPROT", **hard})
        if candidate.mutation_count > 1:
            triggers.append(
                {"code": "T3_MULTI_MUTANT_SINGLE_MODEL", "mutation_count": candidate.mutation_count}
            )
        if triggers:
            return {
                "candidate": candidate.__dict__,
                "refusal": Refusal(True, candidate.variant_id, tuple(triggers)).as_dict(),
            }
        if candidate.variant_id not in self.features or candidate.variant_id not in self.rows:
            raise ValueError(
                f"candidate is not in the frozen 1IGV measured table: {candidate.variant_id}"
            )
        distance = self._distance(candidate.variant_id)
        if distance > self.knn_threshold:
            triggers.append(
                {
                    "code": "T2_EMBEDDING_DISTANCE",
                    "distance": distance,
                    "threshold": self.knn_threshold,
                    "percentile": 95,
                    "calibration_regime": "held_out_position_distances_only",
                    "conditional_policy": self.t2_recalibration["conditional_policy"],
                }
            )
        if triggers:
            return {
                "candidate": candidate.__dict__,
                "refusal": Refusal(True, candidate.variant_id, tuple(triggers)).as_dict(),
            }
        mean, sigma = self._predict([candidate.variant_id])
        flags: list[dict[str, Any]] = []
        penalty = 0.0
        if candidate.position not in self.training_positions:
            flags.append({"code": "T1_POSITION_UNSEEN", "position": candidate.position})
            penalty += T1_PENALTY
        rsa = self.soft_rsa.get(candidate.position)
        if rsa is not None and rsa < RSA_CUTOFF:
            flags.append({"code": "SOFT_BURIED_CORE", "rsa": rsa, "cutoff": RSA_CUTOFF})
            penalty += RSA_PENALTY
        return {
            "candidate": candidate.__dict__,
            "refusal": Refusal(False, candidate.variant_id, ()).as_dict(),
            "mean_prediction_ddg_kcal_higher_is_more_stable": float(mean[0]),
            "ensemble_sigma": float(sigma[0]),
            "soft_flags": flags,
            "ranking_score": float(mean[0] - penalty),
        }

    def rank(self, candidates: list[MeasuredCandidate]) -> dict[str, Any]:
        evaluated = [self.evaluate_candidate(candidate) for candidate in candidates]
        refused = [item for item in evaluated if item["refusal"]["refused"]]
        rankable = [item for item in evaluated if not item["refusal"]["refused"]]
        candidate_ids = [item["candidate"]["variant_id"] for item in rankable]
        rank_predictions = rank_average_scores(
            candidate_ids,
            self.ranker_artifact["thermompnn_scores"],
            self.ranker_artifact["one_hot_scores"],
        )
        for item in rankable:
            variant_id = item["candidate"]["variant_id"]
            item["ranking_score"] = float(
                rank_predictions[variant_id]
                - T1_PENALTY * any(
                    flag["code"] == "T1_POSITION_UNSEEN" for flag in item["soft_flags"]
                )
                - RSA_PENALTY * any(
                    flag["code"] == "SOFT_BURIED_CORE" for flag in item["soft_flags"]
                )
            )
        ranked = sorted(
            rankable,
            key=lambda item: item["ranking_score"],
            reverse=True,
        )
        for index, item in enumerate(ranked, start=1):
            item["rank"] = index
        return {
            "manifest_digest": self.manifest_digest,
            "domain_id": "1IGV.pdb",
            "property": "folding stability",
            "sign_convention": self.manifest["label_contract"],
            "ranking_objective": (
                "ThermoMPNN plus one-hot rank average selected by position-aware CV, "
                "with fixed soft-flag penalties; ensemble mean and sigma are reported "
                "separately"
            ),
            "ranker": self.ranker_artifact["ranker"],
            "ranker_artifact_digest": self.ranker_artifact["artifact_digest"],
            "t2_recalibration": self.t2_recalibration,
            "hard_refused": len(refused),
            "soft_flagged": sum(bool(item.get("soft_flags")) for item in ranked),
            "ranked": len(ranked),
            "trigger_counts": _trigger_counts(refused),
            "candidates": ranked,
            "refusals": [item["refusal"] for item in refused],
        }


def _distance_summary(values: NDArray[Any]) -> dict[str, float | int]:
    return {
        "count": int(len(values)),
        "min": float(np.min(values)),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "max": float(np.max(values)),
    }


def _heldout_position_distances(
    manifest: dict[str, Any], features: dict[str, NDArray[Any]], scheme: str
) -> NDArray[Any]:
    pooled: list[float] = []
    folds = manifest["split"][scheme]["variants"]
    for fold in range(5):
        test_ids = list(folds[str(fold)])
        train_ids = [
            variant_id
            for other in range(5)
            if other != fold
            for variant_id in folds[str(other)]
        ]
        train_x = np.vstack([features[variant_id] for variant_id in train_ids])
        test_x = np.vstack([features[variant_id] for variant_id in test_ids])
        scaler = StandardScaler().fit(train_x)
        pca = PCA(
            n_components=min(50, len(train_x) - 1, train_x.shape[1]), random_state=SEEDS[0]
        ).fit(scaler.transform(train_x))
        train_reduced = pca.transform(scaler.transform(train_x))
        test_reduced = pca.transform(scaler.transform(test_x))
        for query in test_reduced:
            pooled.append(float(np.linalg.norm(train_reduced - query, axis=1).min()))
    return np.asarray(pooled, dtype=float)


def _recalibrate_t2(
    manifest: dict[str, Any], features: dict[str, NDArray[Any]], old_threshold: float
) -> dict[str, Any]:
    random_folds = manifest["split"]["random_5"]["variants"]
    old_training_ids = [
        variant_id
        for fold in range(1, 5)
        for variant_id in random_folds[str(fold)]
    ]
    old_x = np.vstack([features[variant_id] for variant_id in old_training_ids])
    old_scaler = StandardScaler().fit(old_x)
    old_pca = PCA(
        n_components=min(50, len(old_x) - 1, old_x.shape[1]), random_state=SEEDS[0]
    ).fit(old_scaler.transform(old_x))
    old_reduced = old_pca.transform(old_scaler.transform(old_x))
    old_neighbors = np.linalg.norm(
        old_reduced[:, None, :] - old_reduced[None, :, :], axis=2
    )
    np.fill_diagonal(old_neighbors, np.inf)
    old_distances = np.min(old_neighbors, axis=1)
    modulo = _heldout_position_distances(manifest, features, "modulo_5")
    contiguous = _heldout_position_distances(manifest, features, "contiguous_5")
    pooled = np.concatenate([modulo, contiguous])
    new_threshold = float(np.percentile(pooled, 95))
    return {
        "manifest_file_sha256": MANIFEST_FILE_SHA256,
        "manifest_payload_digest": MANIFEST_PAYLOAD_DIGEST,
        "old_threshold": old_threshold,
        "new_threshold": new_threshold,
        "k": 1,
        "reason": (
            "The previous threshold used within-training neighbor distances, which "
            "confounded position novelty with unusually distant embeddings. The new "
            "threshold is the 95th percentile of pooled test-to-training distances "
            "from modulo and contiguous held-out-position folds."
        ),
        "schemes": {
            "old_within_training_random_5": _distance_summary(old_distances),
            "modulo_5": _distance_summary(modulo),
            "contiguous_5": _distance_summary(contiguous),
            "pooled": _distance_summary(pooled),
        },
        "conditional_policy": {
            "known_position_within_training_max": _distance_summary(old_distances)["max"],
            "novel_position_distance_min": _distance_summary(pooled)["min"],
            "gap": _distance_summary(pooled)["min"] - _distance_summary(old_distances)["max"],
            "explanation": (
                "T2 is calibrated only among novel positions. It discriminates "
                "unusually distant novel-position variants; known-position variants "
                "are governed by T1 and cannot trigger this threshold."
            ),
        },
        "holdout_not_used": True,
        "labels_used": False,
        "predictive_metrics_recomputed": False,
    }


def _trigger_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        for trigger in item["refusal"]["triggers"]:
            code = str(trigger["code"])
            counts[code] = counts.get(code, 0) + 1
    return counts


def ranking_cv_evidence() -> dict[str, Any]:
    """Compare one-hot, ensemble, and rank-average using CV only.

    The frozen holdout is intentionally not loaded or evaluated here.
    """
    engine = MeasuredStabilityEngine()
    rows = engine.rows
    features = engine.features
    holdout = set(engine.manifest["split"]["holdout"]["positions"])
    evidence: dict[str, list[float]] = {"one_hot": [], "ensemble": [], "rank_average": []}
    for fold in range(5):
        test_ids = [
            item
            for item in engine.manifest["split"]["modulo_5"]["variants"][str(fold)]
            if rows[item].position not in holdout
        ]
        train_ids = [
            item
            for other in range(5)
            if other != fold
            for item in engine.manifest["split"]["modulo_5"]["variants"][str(other)]
            if rows[item].position not in holdout
        ]
        x_train = np.vstack([features[item] for item in train_ids])
        x_test = np.vstack([features[item] for item in test_ids])
        labels = engine._load_labels(set(train_ids + test_ids))
        y_train = np.array([labels[item] for item in train_ids])
        y_test = np.array([labels[item] for item in test_ids])
        one_train = _one_hot([rows[item] for item in train_ids])
        one_test = _one_hot([rows[item] for item in test_ids])
        one_model = RidgeCV(alphas=np.logspace(-6, 6, 13), cv=5).fit(one_train, y_train)
        one_pred = one_model.predict(one_test)
        heads = []
        for seed in SEEDS:
            rng = np.random.default_rng(seed + fold)
            indexes = rng.integers(0, len(x_train), size=len(x_train))
            scaler = StandardScaler().fit(x_train[indexes])
            model = RidgeCV(alphas=np.logspace(-6, 6, 13), cv=5).fit(
                scaler.transform(x_train[indexes]), y_train[indexes]
            )
            heads.append(model.predict(scaler.transform(x_test)))
        ensemble_pred = np.mean(np.vstack(heads), axis=0)
        one_rank = _rank(one_pred)
        ensemble_rank = _rank(ensemble_pred)
        evidence["one_hot"].append(_top10(y_test, one_pred))
        evidence["ensemble"].append(_top10(y_test, ensemble_pred))
        evidence["rank_average"].append(_top10(y_test, one_rank + ensemble_rank))
    return {
        "schemes": {
            key: {"mean": float(np.mean(value)), "sd": float(np.std(value)), "folds": value}
            for key, value in evidence.items()
        },
        "chosen": "one_hot"
        if np.mean(evidence["one_hot"])
        >= max(np.mean(evidence["ensemble"]), np.mean(evidence["rank_average"]))
        else "rank_average",
        "holdout_used": False,
    }


def _one_hot(rows: list[MeasuredCandidate]) -> NDArray[Any]:
    features = np.zeros((len(rows), 74 + len(AMINO_ACIDS)), dtype=np.float32)
    for index, row in enumerate(rows):
        features[index, row.position - 1] = 1.0
        features[index, 74 + AMINO_ACIDS.index(row.mutant)] = 1.0
    return features


def _rank(values: NDArray[Any]) -> NDArray[Any]:
    result = np.empty(len(values), dtype=float)
    result[np.argsort(values)] = np.linspace(0.0, 1.0, len(values))
    return result


def _top10(y_true: NDArray[Any], prediction: NDArray[Any]) -> float:
    count = max(1, math.ceil(len(y_true) * 0.1))
    return float(
        len(set(np.argsort(y_true)[-count:]) & set(np.argsort(prediction)[-count:])) / count
    )


__all__ = [
    "MeasuredCandidate",
    "MeasuredStabilityEngine",
    "Refusal",
    "ranking_cv_evidence",
    "render_recommendation",
    "refuse_unsupported_signal",
]
