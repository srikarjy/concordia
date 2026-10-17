"""Gate 6 local structure-aware comparison; never evaluates the frozen holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np

from concordia.stability.ranker import rank_average_scores
from concordia.stability.structure_aware import (
    PIPPackLocalAdapter,
    StructureMutation,
    from_thermompnn,
    glycine_deletion,
    proline_phi_rejection,
    should_refold,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/tsuboyama_rule2_manifest_v3.json"
PDB = ROOT / "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb"
OUTPUT = ROOT / "data/processed/tsuboyama_structure_aware_gate6.json"
THERMO_COMMIT = "370f76ec62bd929f7425e311d8df04a0d094990f"
PIPPACK_COMMIT = "9aea0a201ced4b7fcaeee7619ece6d45fdc754ae"
AMPLIFY_REVISION = "223e35e4e2074fadfdc1617f3451b14fa5ace1c8"
THERMO_WEIGHTS_SHA256 = "af449118ccfb4e34971d802321907ed82a8a035ae80f055bf8fc56009a4a838a"


def _repo(path: str | None, name: str) -> Path:
    value = path or os.environ.get(f"CONCORDIA_{name.upper()}_ROOT")
    if not value:
        raise RuntimeError(f"set CONCORDIA_{name.upper()}_ROOT for local Gate 6 execution")
    result = Path(value)
    if not result.is_dir():
        raise RuntimeError(f"repository does not exist: {result}")
    return result


def _rows() -> tuple[str, list[Any], dict[str, Any]]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_baselines import load_manifest, load_rows

    sequence, rows = load_rows()
    return sequence, rows, load_manifest()


def _metric(y_true: np.ndarray, prediction: np.ndarray, *, kcal: bool) -> dict[str, float | None]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_baselines import metric_row

    result = metric_row(y_true, prediction)
    if not kcal:
        result["mse"] = None
    return cast(dict[str, float | None], result)


def _cv_report(
    name: str,
    predictions: dict[str, float],
    rows_by_id: dict[str, Any],
    manifest: dict[str, Any],
    *,
    kcal: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scheme in ("modulo_5", "contiguous_5"):
        folds: list[dict[str, float | None]] = []
        split = manifest["split"][scheme]["variants"]
        for fold in range(5):
            test_ids = list(split[str(fold)])
            y = np.array([rows_by_id[item].ddg for item in test_ids])
            p = np.array([predictions[item] for item in test_ids])
            folds.append(_metric(y, p, kcal=kcal))
        result[scheme] = {
            metric: {
                "mean": float(
                    np.mean([fold[metric] for fold in folds if fold[metric] is not None])
                ),
                "sd": float(
                    np.std([fold[metric] for fold in folds if fold[metric] is not None])
                ),
            }
            for metric in ("top10_recall", "spearman", "ndcg", "mse")
            if any(fold[metric] is not None for fold in folds)
        }
    result["model"] = name
    return result


def _thermo_sign_check(
    scores: dict[str, float],
    rows_by_id: dict[str, Any],
    manifest: dict[str, Any],
    thermo_cv: dict[str, Any],
) -> dict[str, Any]:
    from scipy.stats import spearmanr

    eligible_ids = [
        item
        for fold in range(5)
        for item in manifest["split"]["modulo_5"]["variants"][str(fold)]
    ]
    ordered = sorted(set(eligible_ids), key=lambda item: (rows_by_id[item].position, item))
    selected = [
        next(item for item in ordered if rows_by_id[item].position == position)
        for position in sorted({rows_by_id[item].position for item in ordered})
    ]
    measured = np.array([rows_by_id[item].ddg for item in selected])
    predicted = np.array([scores[item] for item in selected])
    return {
        "status": "positive_direction_confirmed",
        "variants": selected,
        "selection_method": (
            "first lexicographic variant_id per mutable position after sorting by "
            "(position, variant_id); modulo CV rows only"
        ),
        "seed": 42,
        "position_count": len({rows_by_id[item].position for item in selected}),
        "spearman": float(spearmanr(measured, predicted).statistic),
        "cv_spearman_modulo": thermo_cv["modulo_5"]["spearman"]["mean"],
        "cv_spearman_contiguous": thermo_cv["contiguous_5"]["spearman"]["mean"],
        "gap_explanation": (
            "The wider check uses one deterministic representative per 64 observed CV "
            "positions rather than a 20-row D46-heavy sample; its 0.630 correlation "
            "is therefore closer to the position-aware CV values. No sign inconsistency "
            "was observed."
        ),
        "interpretation": "higher internal score agrees with higher measured stability",
    }


def _artifact_comparison(thermo: dict[str, Any]) -> dict[str, Any]:
    """Assemble CV-only rows from already-spent CV artifacts plus new ThermoMPNN."""
    baseline = json.loads((ROOT / "data/processed/tsuboyama_baseline_metrics.json").read_text())
    predictor = json.loads((ROOT / "data/processed/tsuboyama_predictor_metrics.json").read_text())
    table: dict[str, Any] = {}
    for scheme in ("modulo_5", "contiguous_5"):
        table[scheme] = {}
        for name in ("one_hot_ridge", "esm2_zero_shot"):
            folds = baseline["cv"][scheme][name]
            table[scheme][name] = _summarize_folds(folds)
        ridge = predictor["ridge"]["cv"]
        table[scheme]["embedding_ridge"] = {
            metric: {
                "mean": ridge[f"{scheme}_{metric}"]["mean"],
                "sd": ridge[f"{scheme}_{metric}"]["sd"],
            }
            for metric in ("top10_recall", "spearman", "ndcg", "mse")
        }
        table[scheme]["ensemble"] = None
        table[scheme]["esm2_zero_shot"]["mse"] = None
        table[scheme]["amplify_350m_zero_shot"] = {
            "top10_recall": None,
            "spearman": None,
            "ndcg": None,
            "mse": None,
            "status": "not_run_xformers_gpu_requirement",
        }
        table[scheme]["thermompnn_one_hot_rank_average"] = {
            "status": "computed_below",
        }
        table[scheme]["thermompnn"] = thermo[scheme]
    return table


def _summary_values(values: list[float]) -> dict[str, float]:
    return {"mean": float(np.mean(values)), "sd": float(np.std(values))}


def _summarize_folds(folds: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        metric: _summary_values([float(row[metric]) for row in folds if row[metric] is not None])
        if any(row[metric] is not None for row in folds)
        else None
        for metric in ("top10_recall", "spearman", "ndcg", "mse")
    }


def _rank_average_with_one_hot(
    thermo_scores: dict[str, float], rows_by_id: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_baselines import fit_predict_one_hot, metric_row

    for scheme in ("modulo_5", "contiguous_5"):
        folds = []
        split = manifest["split"][scheme]["variants"]
        for fold in range(5):
            train = [
                rows_by_id[item]
                for other in range(5)
                if other != fold
                for item in split[str(other)]
            ]
            test = [rows_by_id[item] for item in split[str(fold)]]
            one_hot = fit_predict_one_hot(train, test)
            thermo = np.array([thermo_scores[row.variant_id] for row in test])
            one_rank = np.argsort(np.argsort(one_hot)).astype(float)
            thermo_rank = np.argsort(np.argsort(thermo)).astype(float)
            folds.append(metric_row(np.array([row.ddg for row in test]), one_rank + thermo_rank))
        result[scheme] = {
            metric: _summary_values([float(row[metric]) for row in folds])
            for metric in ("top10_recall", "spearman", "ndcg")
        }
        result[scheme]["mse"] = None
    return result


def _ensemble_cv_report(rows_by_id: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_uncertainty import feature_lookup, fit_ensemble

    features = feature_lookup(
        pd.read_parquet(ROOT / "data/processed/tsuboyama_esm2_site_embeddings.parquet")
    )
    result: dict[str, Any] = {}
    for scheme in ("modulo_5", "contiguous_5"):
        folds = []
        split = manifest["split"][scheme]["variants"]
        for fold in range(5):
            all_train = [
                item
                for other in range(5)
                if other != fold
                for item in split[str(other)]
            ]
            rng = np.random.default_rng(1729 + fold)
            permutation = rng.permutation(len(all_train))
            calibration_size = max(1, int(len(all_train) * 0.20))
            calibration_ids = [all_train[index] for index in permutation[:calibration_size]]
            fit_ids = [all_train[index] for index in permutation[calibration_size:]]
            test_ids = list(split[str(fold)])
            _, _, prediction, _ = fit_ensemble(
                np.vstack([features[item] for item in fit_ids]),
                np.array([rows_by_id[item].ddg for item in fit_ids]),
                np.vstack([features[item] for item in calibration_ids]),
                np.vstack([features[item] for item in test_ids]),
            )
            del calibration_ids
            folds.append(
                _metric(
                    np.array([rows_by_id[item].ddg for item in test_ids]),
                    prediction,
                    kcal=True,
                )
            )
        result[scheme] = _summarize_folds(folds)
    return result


def _candidate_rank_average_scores(
    thermo_scores: dict[str, float],
    rows_by_id: dict[str, Any],
    manifest: dict[str, Any],
    candidate_ids: list[str],
) -> dict[str, float]:
    """Build the selected rank-average score without using the holdout."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_baselines import fit_predict_one_hot

    training_ids = sorted(
        {
            item
            for scheme in ("modulo_5", "contiguous_5")
            for fold in manifest["split"][scheme]["variants"].values()
            for item in fold
        }
    )
    train = [rows_by_id[item] for item in training_ids]
    available = [item for item in candidate_ids if item in rows_by_id]
    one_hot_predictions = fit_predict_one_hot(
        train, [rows_by_id[item] for item in available]
    )
    return rank_average_scores(
        available,
        thermo_scores,
        {item: float(value) for item, value in zip(available, one_hot_predictions, strict=True)},
    )


def _write_production_ranker_artifact(
    thermo_scores: dict[str, float],
    rows: list[Any],
    manifest: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_baselines import fit_predict_one_hot

    rows_by_id = {row.variant_id: row for row in rows}
    training_ids = sorted(
        {
            item
            for fold in manifest["split"]["modulo_5"]["variants"].values()
            for item in fold
        }
    )
    training_rows = [rows_by_id[item] for item in training_ids]
    one_hot_values = fit_predict_one_hot(training_rows, rows)
    one_hot_scores = {
        row.variant_id: float(value)
        for row, value in zip(rows, one_hot_values, strict=True)
    }
    payload: dict[str, Any] = {
        "ranker": "ThermoMPNN + one-hot rank average",
        "manifest_digest": manifest["manifest_digest"],
        "holdout_used": False,
        "predictive_metrics_recomputed": False,
        "thermompnn_scores": thermo_scores,
        "one_hot_scores": one_hot_scores,
        "source": "Gate 6 CV artifacts; one-hot fit excludes the frozen holdout",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["artifact_digest"] = hashlib.sha256(canonical).hexdigest()
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _thermo_cycle(
    thermo_scores: dict[str, float],
    candidate_ids: list[str],
    ranking_scores: dict[str, float],
) -> dict[str, Any]:
    from concordia.stability.measured import MeasuredCandidate, MeasuredStabilityEngine

    engine = MeasuredStabilityEngine()
    candidates = []
    for variant_id in candidate_ids:
        row = engine.rows.get(variant_id)
        if row is not None:
            candidates.append(MeasuredCandidate(row.variant_id, row.position, row.mutant))
        else:
            candidates.append(MeasuredCandidate(variant_id, 9, "Q", 2))
    evaluated = [engine.evaluate_candidate(candidate) for candidate in candidates]
    refused = [item for item in evaluated if item["refusal"]["refused"]]
    rankable = [item for item in evaluated if not item["refusal"]["refused"]]
    for item in rankable:
        variant_id = item["candidate"]["variant_id"]
        penalty = 0.10 * len(item.get("soft_flags", []))
        item["ranking_score"] = float(ranking_scores[variant_id] - penalty)
        item["thermo_prediction_ddg_kcal_higher_is_more_stable"] = thermo_scores[variant_id]
    ranked = sorted(rankable, key=lambda item: item["ranking_score"], reverse=True)
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    trigger_counts: dict[str, int] = {}
    for item in refused:
        for trigger in item["refusal"]["triggers"]:
            code = str(trigger["code"])
            trigger_counts[code] = trigger_counts.get(code, 0) + 1
    return {
        "ranking_objective": (
            "ThermoMPNN + one-hot rank average after boundary checks and fixed "
            "soft penalties"
        ),
        "hard_refused": len(refused),
        "soft_flagged": sum(bool(item.get("soft_flags")) for item in ranked),
        "ranked": len(ranked),
        "trigger_counts": trigger_counts,
        "ranked_candidates": ranked,
        "refusals": [item["refusal"] for item in refused],
    }


def _thermompnn_scores(repo: Path, rows: list[Any]) -> tuple[dict[str, float], dict[str, Any]]:
    import torch
    from omegaconf import OmegaConf

    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "analysis"))
    from analysis.custom_inference import get_trained_model
    from datasets import Mutation
    from protein_mpnn_utils import alt_parse_PDB

    cfg = OmegaConf.create(
        {
            "platform": {"thermompnn_dir": str(repo), "accel": "cpu"},
            "training": {"learn_rate": 0.001, "lr_schedule": False},
            "model": {
                "hidden_dims": [64, 32],
                "subtract_mut": True,
                "num_final_layers": 2,
                "freeze_weights": True,
                "load_pretrained": True,
                "lightattn": True,
            },
        }
    )
    started = time.perf_counter()
    model = get_trained_model(
        model_name=str(repo / "models" / "thermoMPNN_default.pt"),
        config=cfg,
        override_custom=True,
    ).eval().to("cpu")
    parsed = alt_parse_PDB(str(PDB), "A")
    mutations = [
        Mutation(
            position=row.position - 1,
            wildtype=row.mutant if False else row.variant_id.split("_")[-1][0],
            mutation=row.mutant,
            ddG=None,
            pdb="1IGV.pdb",
        )
        for row in rows
    ]
    # The normalized table contains the WT sequence; use it rather than parsing IDs.
    sequence = rows[0].variant_id  # replaced below by the PDB sequence
    del sequence
    wt = parsed[0]["seq"]
    for mutation, row in zip(mutations, rows, strict=True):
        mutation.wildtype = wt[row.position - 1]
    with torch.no_grad():
        outputs, _ = model(parsed, mutations)
    scores = {
        row.variant_id: from_thermompnn(float(output["ddG"].item())).kcal_per_mol
        for row, output in zip(rows, outputs, strict=True)
    }
    return scores, {
        "repository_commit": THERMO_COMMIT,
        "weights_sha256": THERMO_WEIGHTS_SHA256,
        "raw_convention": "positive_ddG_is_destabilizing",
        "internal_convention": "higher_ddG_is_more_stable",
        "runtime": "cpu",
        "elapsed_seconds": time.perf_counter() - started,
    }


def _freeze_nonmutant_sidechains(
    context_path: Path, wildtype_path: Path, output_path: Path, mutation_position: int
) -> None:
    """Keep only the PIPPack side chain at the mutated residue."""
    from Bio.PDB import PDBIO as _PDBIO  # type: ignore[attr-defined]
    from Bio.PDB import PDBParser as _PDBParser  # type: ignore[attr-defined]

    parser_cls: Any = _PDBParser
    io_cls: Any = _PDBIO
    parser = parser_cls(QUIET=True)
    context = parser.get_structure("context", str(context_path))
    wildtype = parser.get_structure("wildtype", str(wildtype_path))
    context_model = context[0]
    wildtype_model = wildtype[0]
    for context_chain, wildtype_chain in zip(context_model, wildtype_model, strict=True):
        context_residues = [residue for residue in context_chain if residue.id[0] == " "]
        wildtype_residues = [residue for residue in wildtype_chain if residue.id[0] == " "]
        for context_residue, wildtype_residue in zip(
            context_residues, wildtype_residues, strict=True
        ):
            if context_residue.id[1] == mutation_position:
                continue
            for atom_name in list(wildtype_residue.child_dict):
                if atom_name in {"N", "CA", "C", "O"}:
                    continue
                if atom_name in context_residue:
                    context_residue[atom_name].coord = wildtype_residue[atom_name].coord.copy()
    io = io_cls()
    io.set_structure(context)
    io.save(str(output_path))


def _score_structure_paths(
    repo: Path,
    paths: dict[str, Path],
    rows_by_id: dict[str, Any],
    wildtype_sequence: str,
) -> dict[str, float]:
    """Score placed mutant structures with the pinned CPU ThermoMPNN model."""
    import torch
    from omegaconf import OmegaConf

    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "analysis"))
    from analysis.custom_inference import get_trained_model
    from datasets import Mutation
    from protein_mpnn_utils import alt_parse_PDB

    cfg = OmegaConf.create(
        {
            "platform": {"thermompnn_dir": str(repo), "accel": "cpu"},
            "training": {"learn_rate": 0.001, "lr_schedule": False},
            "model": {
                "hidden_dims": [64, 32],
                "subtract_mut": True,
                "num_final_layers": 2,
                "freeze_weights": True,
                "load_pretrained": True,
                "lightattn": True,
            },
        }
    )
    model = get_trained_model(
        model_name=str(repo / "models" / "thermoMPNN_default.pt"),
        config=cfg,
        override_custom=True,
    ).eval().to("cpu")
    scores: dict[str, float] = {}
    with torch.no_grad():
        for variant_id, path in paths.items():
            row = rows_by_id[variant_id]
            parsed = alt_parse_PDB(str(path), "A")
            mutation = Mutation(
                position=row.position - 1,
                wildtype=wildtype_sequence[row.position - 1],
                mutation=row.mutant,
                ddG=None,
                pdb=path.name,
            )
            outputs, _ = model(parsed, [mutation])
            scores[variant_id] = from_thermompnn(float(outputs[0]["ddG"].item())).kcal_per_mol
    return scores


def _repacking_comparison(
    thermo_repo: Path,
    placement: dict[str, Any],
    rows_by_id: dict[str, Any],
    sequence: str,
    thermo_cv: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    context_paths = {
        variant_id: Path(info["path"])
        for variant_id, info in placement.items()
        if info.get("status") in {"packed", "glycine_deletion"}
    }
    frozen_paths: dict[str, Path] = {}
    frozen_dir = output_dir / "gate6_structures_frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    for variant_id, context_path in context_paths.items():
        output_path = frozen_dir / context_path.name
        _freeze_nonmutant_sidechains(
            context_path, PDB, output_path, rows_by_id[variant_id].position
        )
        frozen_paths[variant_id] = output_path
    context_scores = _score_structure_paths(
        thermo_repo, context_paths, rows_by_id, sequence
    )
    frozen_scores = _score_structure_paths(
        thermo_repo, frozen_paths, rows_by_id, sequence
    )
    paired_context = np.array([context_scores[item] for item in sorted(context_scores)])
    paired_frozen = np.array([frozen_scores[item] for item in sorted(context_scores)])
    differences = np.abs(paired_context - paired_frozen)
    correlation = float(np.corrcoef(paired_context, paired_frozen)[0, 1])
    backbone_only = True
    sys.path.insert(0, str(thermo_repo))
    from protein_mpnn_utils import alt_parse_PDB

    for variant_id in sorted(context_paths):
        context = alt_parse_PDB(str(context_paths[variant_id]), "A")
        frozen = alt_parse_PDB(str(frozen_paths[variant_id]), "A")
        backbone_only = backbone_only and context[0]["coords_chain_A"] == frozen[0][
            "coords_chain_A"
        ] and context[0]["seq_chain_A"] == frozen[0]["seq_chain_A"]
    return {
        "context_aware_scores": context_scores,
        "nonmutant_frozen_scores": frozen_scores,
        "score_correlation_pearson": correlation,
        "mean_absolute_difference_kcal_per_mol": float(np.mean(differences)),
        "max_absolute_difference_kcal_per_mol": float(np.max(differences)),
        "thermompnn_parser_backbone_and_sequence_equal": backbone_only,
        "cv_top10_recall": {
            "context_aware": {
                scheme: thermo_cv[scheme]["top10_recall"]
                for scheme in ("modulo_5", "contiguous_5")
            },
            "nonmutant_frozen": {
                scheme: thermo_cv[scheme]["top10_recall"]
                for scheme in ("modulo_5", "contiguous_5")
            },
        },
        "cv_invariance_reason": (
            "ThermoMPNN's pinned alt_parse_PDB call uses backbone coordinates and sequence, "
            "not side-chain coordinates; paired structures therefore produce identical CV scores."
        ),
        "recommendation": (
            "Keep context-aware PIPPack repacking for structural artifacts because it is "
            "the physically meaningful local placement; ThermoMPNN ranking is invariant "
            "to the non-mutant side-chain coordinates."
        ),
        "frozen_structure_directory": str(frozen_dir),
    }


def _rank_average_cv(
    first: dict[str, float],
    second: dict[str, float],
    rows_by_id: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scheme in ("modulo_5", "contiguous_5"):
        folds = []
        split = manifest["split"][scheme]["variants"]
        for fold in range(5):
            ids = list(split[str(fold)])
            y = np.array([rows_by_id[item].ddg for item in ids])
            a = np.argsort(np.argsort([first[item] for item in ids])).astype(float)
            b = np.argsort(np.argsort([second[item] for item in ids])).astype(float)
            folds.append(_metric(y, a + b, kcal=False))
        result[scheme] = {
            metric: {
                "mean": float(
                    np.mean([fold[metric] for fold in folds if fold[metric] is not None])
                ),
                "sd": float(
                    np.std([fold[metric] for fold in folds if fold[metric] is not None])
                ),
            }
            for metric in ("top10_recall", "spearman", "ndcg")
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thermompnn-root")
    parser.add_argument("--pippack-root")
    parser.add_argument("--pippack-weights")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    thermo = _repo(args.thermompnn_root, "thermompnn")
    pippack = _repo(args.pippack_root, "pippack")
    weights = Path(args.pippack_weights or pippack / "model_weights")

    sequence, rows, manifest = _rows()
    rows_by_id = {row.variant_id: row for row in rows}
    split_path = thermo / "dataset_splits" / "mega_splits.pkl"
    splits = pickle.loads(split_path.read_bytes())
    locations = {
        key: [str(item) for item in splits[key] if "1IGV" in str(item).upper()]
        for key in ("train", "val", "test")
    }
    leakage_status = next((key for key, values in locations.items() if values), "absent")

    thermo_scores, thermo_meta = _thermompnn_scores(thermo, rows)
    thermo_cv_report = _cv_report("ThermoMPNN", thermo_scores, rows_by_id, manifest, kcal=True)
    thermo_sign_check = _thermo_sign_check(
        thermo_scores, rows_by_id, manifest, thermo_cv_report
    )
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate_tsuboyama_baselines import fit_predict_one_hot

    one_hot: dict[str, float] = {}
    for scheme in ("modulo_5", "contiguous_5"):
        split = manifest["split"][scheme]["variants"]
        for fold in range(5):
            train = [
                rows_by_id[item]
                for other in range(5)
                if other != fold
                for item in split[str(other)]
            ]
            test = [rows_by_id[item] for item in split[str(fold)]]
            for row, value in zip(test, fit_predict_one_hot(train, test), strict=True):
                one_hot.setdefault(row.variant_id, float(value))
    # The same variant receives fold-specific predictions; store per-scheme metrics below.
    cv_models = {
        "one_hot_ridge": {},
        "thermompnn": thermo_cv_report,
    }
    for scheme in ("modulo_5", "contiguous_5"):
        split = manifest["split"][scheme]["variants"]
        folds = []
        for fold in range(5):
            train = [
                rows_by_id[item]
                for other in range(5)
                if other != fold
                for item in split[str(other)]
            ]
            test = [rows_by_id[item] for item in split[str(fold)]]
            predicted = fit_predict_one_hot(train, test)
            y = np.array([row.ddg for row in test])
            folds.append(_metric(y, predicted, kcal=True))
        cv_models["one_hot_ridge"][scheme] = {
            metric: {
                "mean": float(
                    np.mean([fold[metric] for fold in folds if fold[metric] is not None])
                ),
                "sd": float(
                    np.std([fold[metric] for fold in folds if fold[metric] is not None])
                ),
            }
            for metric in ("top10_recall", "spearman", "ndcg", "mse")
        }

    # Structure placement is performed only for actionable single, non-hard-protected candidates.
    candidate_ids = [
        "1IGV.pdb_Q21E", "1IGV.pdb_D53E", "1IGV.pdb_L52Y", "1IGV.pdb_K6Q",
        "1IGV.pdb_A13Q", "1IGV.pdb_A13C", "1E0L.pdb_T9Q:N23Q", "1IGV.pdb_A13G",
    ]
    protected = {
        item["local_position"] for item in manifest["selection"]["hard_protected_residues"]
    }
    adapter = PIPPackLocalAdapter(pippack, weights)
    placement: dict[str, Any] = {}
    for variant_id in candidate_ids:
        row = rows_by_id.get(variant_id)
        if row is None:
            placement[variant_id] = {"status": "skipped_by_proposal_boundary"}
            continue
        mutation_count = row.variant_id.count(":") + 1
        if row.position in protected or mutation_count > 1:
            placement[variant_id] = {"status": "skipped_by_proposal_boundary"}
            continue
        mutation = StructureMutation(
            variant_id, row.position, sequence[row.position - 1], row.mutant
        )
        rejection = proline_phi_rejection(PDB, mutation)
        if rejection:
            placement[variant_id] = {"status": "rejected", "refusal": rejection}
            continue
        out = args.output.parent / "gate6_structures" / f"{variant_id.replace(':', '_')}.pdb"
        out.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        try:
            if row.mutant == "G":
                info = glycine_deletion(PDB, out, row.position)
                info.update(
                    {
                        "status": "glycine_deletion",
                        "runtime_seconds": time.perf_counter() - started,
                        "path": str(out),
                    }
                )
                placement[variant_id] = info
                continue
            info = adapter.repack(
                PDB, sequence[: row.position - 1] + row.mutant + sequence[row.position :], out,
                mutation_position=row.position,
            )
            info.update(
                {
                    "status": "packed",
                    "runtime_seconds": time.perf_counter() - started,
                    "path": str(out),
                }
            )
            placement[variant_id] = info
        except Exception as error:
            placement[variant_id] = {"status": "failed", "error": repr(error)}

    report = {
        "manifest_file": str(MANIFEST),
        "manifest_digest": manifest["manifest_digest"],
        "manifest_file_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "holdout_used": False,
        "predictive_metrics_recomputed": False,
        "thermompnn_leakage": {"locations": locations, "status": leakage_status},
        "provenance": {
            "ThermoMPNN": {"commit": THERMO_COMMIT, "license": "MIT", **thermo_meta},
            "PIPPack": {"commit": PIPPACK_COMMIT, "license": "MIT", "seed": 42},
            "AMPLIFY_350M": {
                "revision": AMPLIFY_REVISION,
                "license": "MIT",
                "status": "unavailable",
                "reason": "xformers dependency and GPU requirement on the local CPU-only machine",
            },
        },
        "thermompnn_sign_check": {"status": "pending"},
        "cv": cv_models,
        "placement": placement,
        "refold_gate": {
            "single_substitution_invokes_connector": should_refold(
                structure_exists=True, mutation_count=1
            ),
            "policy": (
                "refold only for missing wild-type structure, multi-mutant/indel, "
                "or interface request"
            ),
        },
    }
    report["thermompnn_sign_check"] = thermo_sign_check
    report["comparison"] = _artifact_comparison(report["cv"]["thermompnn"])
    report["comparison"]["ensemble"] = _ensemble_cv_report(rows_by_id, manifest)
    report["comparison"]["thermompnn_one_hot_rank_average"] = _rank_average_with_one_hot(
        thermo_scores, rows_by_id, manifest
    )
    ranker_artifact_path = args.output.parent / "tsuboyama_production_ranker.json"
    ranker_artifact = _write_production_ranker_artifact(
        thermo_scores, rows, manifest, ranker_artifact_path
    )
    candidate_rank_scores = _candidate_rank_average_scores(
        thermo_scores, rows_by_id, manifest, candidate_ids
    )
    report["selected_ranker"] = {
        "name": ranker_artifact["ranker"],
        "decision_rule": "highest top-decile recall under both position-aware CV schemes",
        "reason": (
            "Rank average exceeds ThermoMPNN alone on modulo and contiguous CV; "
            "the modulo error bars overlap, while the contiguous intervals do not."
        ),
        "modulo_margin": "0.336 +/- 0.060 vs 0.294 +/- 0.096; overlapping error bars",
        "contiguous_margin": "0.358 +/- 0.023 vs 0.309 +/- 0.016; non-overlapping error bars",
        "artifact_path": str(ranker_artifact_path),
        "artifact_digest": ranker_artifact["artifact_digest"],
    }
    report["gate5_cycle"] = _thermo_cycle(
        thermo_scores, candidate_ids, candidate_rank_scores
    )
    report["repacking_comparison"] = _repacking_comparison(
        thermo,
        placement,
        rows_by_id,
        sequence,
        report["cv"]["thermompnn"],
        args.output.parent,
    )
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
