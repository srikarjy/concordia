"""Build the frontend-ready measured-stability integration artifact.

This is an assembly step over already-frozen, already-evaluated artifacts.  It
does not load a model, inspect labels, or run a holdout evaluation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from concordia.runtime.model_registry import MODEL_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MANIFEST = ROOT / "data" / "manifests" / "tsuboyama_rule2_manifest_v3.json"
OUTPUT = PROCESSED / "concordia_measured_stability_integration.json"


def _read(name: str) -> dict[str, Any]:
    return json.loads((PROCESSED / name).read_text(encoding="utf-8"))


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def build() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gate6 = _read("tsuboyama_structure_aware_gate6.json")
    predictor = _read("tsuboyama_predictor_metrics.json")
    baseline = _read("tsuboyama_baseline_metrics.json")
    uncertainty = _read("tsuboyama_uncertainty_metrics.json")
    t2 = _read("tsuboyama_t2_recalibration.json")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest": {
            "path": str(MANIFEST.relative_to(ROOT)),
            "payload_digest": manifest["manifest_digest"],
            "file_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            "holdout_used": False,
        },
        "domain": "1IGV.pdb",
        "property": "folding stability",
        "sign_convention": manifest["label_contract"],
        "ranker": gate6["selected_ranker"],
        "ranked_candidates": gate6["gate5_cycle"]["ranked_candidates"],
        "refusals": gate6["gate5_cycle"]["refusals"],
        "counts": {
            "hard_refused": gate6["gate5_cycle"]["hard_refused"],
            "soft_flagged": gate6["gate5_cycle"]["soft_flagged"],
            "ranked": gate6["gate5_cycle"]["ranked"],
            "trigger_counts": gate6["gate5_cycle"]["trigger_counts"],
        },
        "uncertainty": {
            "ensemble": uncertainty["ensemble"],
            "holdout_policy_audit": {
                "used_for_metrics": False,
                "interval_summary": uncertainty["holdout"],
                "note": "Stored Gate 4 result; not recomputed by this build step.",
            },
            "reliability_diagram": uncertainty["reliability_diagram"],
        },
        "t2_policy": t2,
        "provenance": {
            "models": [dict(item) for item in MODEL_REGISTRY],
            "dataset": {
                "citation": "Tsuboyama et al., Nature 620:434-444 (2023)",
                "zenodo_record": "10.5281/zenodo.7992926",
                "version": "v2_230420",
                "license": "CC-BY 4.0",
            },
            "secret_policy": "Credentials are never serialized into this artifact.",
        },
        "gate2_baselines": baseline,
        "gate3_predictor": predictor,
        "gate6_structure_aware": gate6,
    }
    payload["artifact_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def main() -> None:
    artifact = build()
    OUTPUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUTPUT), "artifact_sha256": artifact["artifact_sha256"]}))


if __name__ == "__main__":
    main()
