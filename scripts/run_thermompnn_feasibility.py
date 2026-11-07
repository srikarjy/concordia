#!/usr/bin/env python3
"""Record the preregistered, fail-closed ThermoMPNN CPU feasibility pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from concordia.protein_xai.thermompnn import (
    FeasibilityPilot,
    PilotRequest,
    build_feasibility_record,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports/thermompnn-feasibility/2026-10-20-1igv-s1a.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thermompnn-root", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    request = PilotRequest(
        structure_path=(
            ROOT / "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb"
        ),
        manifest_path=ROOT / "data/manifests/tsuboyama_rule2_manifest_v3.json",
        chain_id="A",
        position=1,
        wildtype="S",
        mutant="A",
        variant_id="1IGV.pdb_S1A",
    )
    record = build_feasibility_record(FeasibilityPilot(request, args.thermompnn_root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        hashlib.sha256(encoded.encode()).hexdigest() + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": record["status"], "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
