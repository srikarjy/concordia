"""Build a counterfactual selection: each antibody's predicted paratope mutated to alanine.

The paratope is taken from the model's own prediction (antibody residues within
4.5 A of the antigen in WORKDIR/{PDB}.pred.cif), never from the crystal. If a
re-prediction with those residues removed still places the antigen in the same
spot, the pose did not depend on the interface it claims.

    uv run --no-project --with biopython python scripts/paratope_counterfactual.py \\
        SELECTION.json WORKDIR OUT_SELECTION.json

Run the benchmark on OUT_SELECTION.json in a separate workdir, then copy each
{PDB}.pred.cif from it into WORKDIR as {PDB}.perturbed.cif for verify_benchmark.py.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from structure_measurements import ANTIBODY_ROLES, interface_residues

ROLE = {"A": "H", "B": "L"}  # Boltz output chain -> selection role


def paratope(pred: Path) -> dict[str, list[int]]:
    found: dict[str, set[int]] = {"H": set(), "L": set()}
    for chain, index in interface_residues(pred, ANTIBODY_ROLES):
        found[ROLE[chain]].add(index)
    return {role: sorted(indices) for role, indices in found.items()}


def mutate(sequence: str, positions: list[int]) -> str:
    residues = list(sequence)
    for i in positions:
        residues[i] = "A"
    return "".join(residues)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("selection", type=Path)
    parser.add_argument("workdir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    out = copy.deepcopy(selection)
    out["counterfactual"] = {
        "rule": "antibody residues within 4.5 A of the antigen in the model's own top "
        "prediction, mutated to alanine",
        "source_workdir": str(args.workdir),
        "mutated": {},
    }
    kept = []
    for entry in out["complexes"]:
        pred = args.workdir / f"{entry['pdb_id']}.pred.cif"
        if not pred.exists():
            continue
        sites = paratope(pred)
        for role, positions in sites.items():
            entry["sequences"][role] = mutate(entry["sequences"][role], positions)
        out["counterfactual"]["mutated"][entry["pdb_id"]] = sites
        kept.append(entry)
    out["complexes"] = kept
    args.output.write_text(json.dumps(out, indent=2) + "\n")
    print({pdb: sum(map(len, s.values())) for pdb, s in out["counterfactual"]["mutated"].items()})


if __name__ == "__main__":
    main()
