"""Antibody-antigen DockQ with the heavy and light chains treated as one partner.

DockQ scores chain pairs. The convention for antibody-antigen docking is one
interface, antibody (H+L) against antigen, so both structures are rewritten
with H and L merged into chain A (L residues renumbered by +1000) and the
antigen as chain B before DockQ runs. CAPRI classes follow the DockQ paper:
incorrect < 0.23 <= acceptable < 0.49 <= medium < 0.80 <= high.

Needs biopython and DockQ, which are not project dependencies:

    uv run --no-project --with DockQ python scripts/antibody_dockq.py PRED.cif CRYSTAL.cif \
        --chains H=H,L=L,A=A
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from Bio.PDB import PDBIO, MMCIFParser
from Bio.PDB.Chain import Chain
from Bio.PDB.Model import Model
from Bio.PDB.Structure import Structure

L_OFFSET = 1000
# Boltz relabels output chains A, B, C in input order (H, L, antigen).
PREDICTED_CHAINS = {"H": "A", "L": "B", "A": "C"}


def capri_class(dockq: float) -> str:
    if dockq >= 0.80:
        return "high"
    if dockq >= 0.49:
        return "medium"
    if dockq >= 0.23:
        return "acceptable"
    return "incorrect"


def _merged(path: Path, chains: dict[str, str], out: Path) -> None:
    source = MMCIFParser(QUIET=True).get_structure("s", str(path))[0]
    model = Model(0)
    antibody, antigen = Chain("A"), Chain("B")
    for role, target, offset in (("H", antibody, 0), ("L", antibody, L_OFFSET), ("A", antigen, 0)):
        for residue in list(source[chains[role]]):
            if residue.id[0] != " ":
                continue
            residue = residue.copy()
            residue.detach_parent()
            residue.id = (" ", residue.id[1] + offset, residue.id[2])
            target.add(residue)
    model.add(antibody)
    model.add(antigen)
    structure = Structure("merged")
    structure.add(model)
    io = PDBIO()
    io.set_structure(structure)
    io.save(str(out))


def antibody_dockq(pred_cif: Path, crystal_cif: Path, auth_chains: dict[str, str]) -> dict:
    """Return DockQ, Fnat, iRMSD, LRMSD and CAPRI class for antibody vs antigen."""
    with tempfile.TemporaryDirectory() as tmp:
        model, native = Path(tmp) / "model.pdb", Path(tmp) / "native.pdb"
        _merged(pred_cif, PREDICTED_CHAINS, model)
        _merged(crystal_cif, auth_chains, native)
        report = Path(tmp) / "dockq.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "DockQ.DockQ",
                str(model),
                str(native),
                "--mapping",
                "AB:AB",
                "--json",
                str(report),
            ],
            check=True,
            capture_output=True,
        )
        payload = json.loads(report.read_text())
    best = payload["best_result"]["AB"]
    dockq = float(best["DockQ"])
    return {
        "dockq": round(dockq, 3),
        "fnat": round(float(best["fnat"]), 3),
        "irmsd": round(float(best["iRMSD"]), 2),
        "lrmsd": round(float(best["LRMSD"]), 2),
        "capri_class": capri_class(dockq),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pred", type=Path)
    parser.add_argument("crystal", type=Path)
    parser.add_argument("--chains", default="H=H,L=L,A=A", help="role=auth_chain for the crystal")
    args = parser.parse_args()
    chains = dict(item.split("=") for item in args.chains.split(","))
    print(json.dumps(antibody_dockq(args.pred, args.crystal, chains)))


if __name__ == "__main__":
    main()
