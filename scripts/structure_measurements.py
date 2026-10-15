"""Measure the structure signals that concordia.verification.structure_rules assesses.

Inputs are Boltz-style mmCIF files with chains A (heavy), B (light), C (antigen).
Needs biopython, which is not a project dependency.
"""

from __future__ import annotations

import copy
from pathlib import Path

from Bio.PDB import MMCIFParser, NeighborSearch
from Bio.PDB.SASA import ShrakeRupley

ANTIBODY, ANTIGEN = ("A", "B"), "C"
CONTACT = 4.5
CLASH = 2.2
# Variable domains end near residue 120 (heavy) and 110 (light) in sequence order.
VARIABLE_LENGTH = {"A": 120, "B": 110}


def load(path: Path):
    return MMCIFParser(QUIET=True).get_structure(path.stem, str(path))[0]


def _interface(model) -> tuple[set[tuple[str, int, int]], int]:
    """Antibody-antigen residue pairs (by sequence index) in contact, and clash count."""
    index = {chain.id: {res.id: i for i, res in enumerate(chain)} for chain in model}
    antibody = [a for c in ANTIBODY for a in model[c].get_atoms() if a.element != "H"]
    search = NeighborSearch(antibody)
    pairs, clashes = set(), 0
    for atom in model[ANTIGEN].get_atoms():
        if atom.element == "H":
            continue
        for other in search.search(atom.coord, CONTACT):
            ab_res, ag_res = other.get_parent(), atom.get_parent()
            chain = ab_res.get_parent().id
            pairs.add((chain, index[chain][ab_res.id], index[ANTIGEN][ag_res.id]))
            if atom - other < CLASH:
                clashes += 1
    return pairs, clashes


def _sasa(model, keep: str) -> float:
    part = copy.deepcopy(model)
    for chain in list(part):
        if chain.id not in keep:
            part.detach_child(chain.id)
    ShrakeRupley().compute(part, level="M")
    return float(part.sasa)


def physical(path: Path) -> dict:
    model = load(path)
    pairs, clashes = _interface(model)
    antibody_residues = {(chain, i) for chain, i, _ in pairs}
    in_variable = sum(i < VARIABLE_LENGTH[chain] for chain, i in antibody_residues)
    buried = _sasa(model, "AB") + _sasa(model, "C") - _sasa(model, "ABC")
    return {
        "clash_count": clashes,
        "variable_domain_fraction": round(in_variable / max(1, len(antibody_residues)), 3),
        "buried_surface_area": round(buried, 1),
    }


def interface_agreement(reference: Path, other: Path) -> float:
    """Fraction of the reference prediction's contacts that the other prediction reproduces."""
    first, _ = _interface(load(reference))
    second, _ = _interface(load(other))
    return round(len(first & second) / max(1, len(first)), 3)
