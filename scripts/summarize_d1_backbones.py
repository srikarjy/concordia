"""Summarize local geometry and secondary structure of D1 backbones."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from Bio.PDB import DSSP, PDBIO, PDBParser

ROOT = Path("data/design/d1_1igv_pilot_v2")
OUTPUT = Path("results/d1_backbone_sanity.json")


def main() -> None:
    parser = PDBParser(QUIET=True)
    rows: list[dict[str, Any]] = []
    for pdb_path in sorted(ROOT.glob("backbone_*.pdb")):
        structure = parser.get_structure(pdb_path.stem, str(pdb_path))
        model = structure[0]
        chain = model["A"]
        residues = [residue for residue in chain if residue.id[0] == " " and "CA" in residue]
        coordinates = np.asarray([residue["CA"].coord for residue in residues], dtype=np.float64)
        center = coordinates.mean(axis=0)
        radius_gyration = float(np.sqrt(np.mean(np.sum((coordinates - center) ** 2, axis=1))))
        adjacent_distances = np.linalg.norm(np.diff(coordinates, axis=0), axis=1)
        breaks = [
            index + 1
            for index, distance in enumerate(adjacent_distances)
            if float(distance) > 4.2
        ]
        # NVIDIA's returned PDBs have blank element columns. PDBIO rewrites the
        # same parsed coordinates into a DSSP-compatible representation; it does
        # not re-predict or alter the structure.
        with tempfile.NamedTemporaryFile(suffix=".pdb") as normalized:
            io = PDBIO()
            io.set_structure(structure)
            io.save(normalized.name)
            dssp = DSSP(model, normalized.name, dssp="mkdssp")
        codes = [dssp[(chain.id, residue.id)][2] for residue in residues]
        helix = sum(code in {"H", "G", "I"} for code in codes)
        sheet = sum(code in {"E", "B"} for code in codes)
        loop = len(codes) - helix - sheet
        rows.append(
            {
                "backbone": pdb_path.name,
                "chain": "A",
                "length": len(residues),
                "secondary_structure": {
                    "helix_residues": helix,
                    "sheet_residues": sheet,
                    "loop_residues": loop,
                    "dssp_codes": "".join(codes),
                },
                "radius_gyration_angstrom": radius_gyration,
                "ca_ca_max_angstrom": float(np.max(adjacent_distances)),
                "ca_breaks_over_4_2_angstrom": breaks,
                "implausible_compaction_flag": radius_gyration < 5.0,
            }
        )
    OUTPUT.write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
