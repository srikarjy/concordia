"""Prepare the pinned, label-free 1IGV OOD calibration before serving.

Existing outputs are checked but never overwritten. A new calibration requires
an explicitly reviewed new asset manifest and digest pin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from concordia.stability.assets import resolve_asset_root, verify_assets
from concordia.stability.measured import (
    EMBEDDING_PATH,
    MANIFEST_PATH,
    T2_RECALIBRATION_PATH,
    UNCERTAINTY_PATH,
    _recalibrate_t2,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path)
    args = parser.parse_args()
    root = resolve_asset_root(args.asset_root)
    manifest = verify_assets(root, include_calibration=False)
    selected = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    frame = pd.read_parquet(root / EMBEDDING_PATH)
    columns = [column for column in frame.columns if column.startswith("f")]
    matrix = frame[columns].to_numpy(dtype=np.float32)
    features = {
        str(variant_id): matrix[index] for index, variant_id in enumerate(frame["variant_id"])
    }
    uncertainty = json.loads((root / UNCERTAINTY_PATH).read_text(encoding="utf-8"))
    prepared = _recalibrate_t2(selected, features, float(uncertainty["ood"]["knn_threshold"]))
    raw = (json.dumps(prepared, indent=2, sort_keys=True) + "\n").encode()
    expected = manifest["files"][str(T2_RECALIBRATION_PATH)]["sha256"]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("prepared calibration differs from the frozen approved output")
    target = root / T2_RECALIBRATION_PATH
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError("existing calibration differs from the frozen approved output")
        print(f"existing calibration verified: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    verify_assets(root)
    print(f"frozen calibration prepared: {target}")


if __name__ == "__main__":
    main()
