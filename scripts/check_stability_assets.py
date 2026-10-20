"""Fail early when frozen 1IGV regression assets are absent.

This checks availability only; T2 owns trusted digests and distribution. It must
not deserialize models, generate replacements, or silently skip regression tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED = (
    "data/manifests/tsuboyama_rule2_manifest_v3.json",
    "data/processed/tsuboyama_v2_230420_normalized.csv",
    "data/processed/tsuboyama_esm2_site_embeddings.parquet",
    "data/processed/tsuboyama_ensemble_artifacts.joblib",
    "data/processed/tsuboyama_production_ranker.json",
    "data/processed/tsuboyama_uncertainty_metrics.json",
    "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb",
)


def missing_assets(root: Path) -> list[str]:
    return [name for name in REQUIRED if not (root / name).is_file()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    missing = missing_assets(args.root)
    if missing:
        parser.exit(
            1,
            "Frozen 1IGV regression prerequisites are missing:\n"
            + "\n".join(f"  {name}" for name in missing)
            + "\nSee docs/installation-and-checks.md. T2 must provide the verified "
            "asset bundle; no model retraining or test skipping is implied.\n",
        )
    print("All 7 frozen 1IGV input files are present (availability only, not integrity).")


if __name__ == "__main__":
    main()
