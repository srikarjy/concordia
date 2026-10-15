"""Measure the structure signals that concordia.verification.structure_rules assesses.

Inputs are mmCIF files. Chain roles default to the Boltz antibody-antigen layout
(A heavy, B light, C antigen) and can be overridden for any other complex, such
as a designed binder against its target.

``variable_domain_fraction`` is antibody-specific: it asks whether the contacts
sit in the variable domain, where real antibodies bind. It is reported only when
the roles carry variable-domain lengths, so a de novo binder is measured on
clashes and buried surface alone rather than on a signal that does not apply.

Needs biopython, which is not a project dependency.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from Bio.PDB import MMCIFParser, NeighborSearch
from Bio.PDB.SASA import ShrakeRupley

CONTACT = 4.5
CLASH = 2.2


@dataclass(frozen=True)
class ChainRoles:
    """Which chains form each side of the interface being measured."""

    receptor: tuple[str, ...]
    ligand: tuple[str, ...]
    # Sequence index where each receptor chain's variable domain ends, when the
    # concept applies. Empty for anything that is not an antibody.
    variable_length: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if set(self.receptor) & set(self.ligand):
            raise ValueError("receptor and ligand chains must be disjoint")
        if not self.receptor or not self.ligand:
            raise ValueError("both sides of the interface need at least one chain")


# Boltz relabels output chains A, B, C in input order (heavy, light, antigen).
ANTIBODY_ROLES = ChainRoles(
    receptor=("A", "B"), ligand=("C",), variable_length={"A": 120, "B": 110}
)
# RFdiffusion writes the designed binder as its own chain alongside the target.
BINDER_ROLES = ChainRoles(receptor=("A",), ligand=("B",))


def load(path: Path):
    return MMCIFParser(QUIET=True).get_structure(path.stem, str(path))[0]


def _interface(model, roles: ChainRoles) -> tuple[set[tuple[str, int, int]], int]:
    """Receptor-ligand residue pairs (by sequence index) in contact, and clash count."""
    index = {chain.id: {res.id: i for i, res in enumerate(chain)} for chain in model}
    receptor = [a for c in roles.receptor for a in model[c].get_atoms() if a.element != "H"]
    search = NeighborSearch(receptor)
    pairs, clashes = set(), 0
    for ligand_chain in roles.ligand:
        for atom in model[ligand_chain].get_atoms():
            if atom.element == "H":
                continue
            for other in search.search(atom.coord, CONTACT):
                receptor_residue, ligand_residue = other.get_parent(), atom.get_parent()
                chain = receptor_residue.get_parent().id
                pairs.add(
                    (
                        chain,
                        index[chain][receptor_residue.id],
                        index[ligand_chain][ligand_residue.id],
                    )
                )
                if atom - other < CLASH:
                    clashes += 1
    return pairs, clashes


def _sasa(model, keep: tuple[str, ...]) -> float:
    part = copy.deepcopy(model)
    for chain in list(part):
        if chain.id not in keep:
            part.detach_child(chain.id)
    ShrakeRupley().compute(part, level="M")
    return float(part.sasa)


def physical(path: Path, roles: ChainRoles = ANTIBODY_ROLES) -> dict:
    model = load(path)
    pairs, clashes = _interface(model, roles)
    receptor_residues = {(chain, i) for chain, i, _ in pairs}
    both = roles.receptor + roles.ligand
    buried = _sasa(model, roles.receptor) + _sasa(model, roles.ligand) - _sasa(model, both)
    measured = {"clash_count": clashes, "buried_surface_area": round(buried, 1)}
    if roles.variable_length:
        in_variable = sum(
            i < roles.variable_length[chain]
            for chain, i in receptor_residues
            if chain in roles.variable_length
        )
        measured["variable_domain_fraction"] = round(
            in_variable / max(1, len(receptor_residues)), 3
        )
    return measured


def interface_residues(path: Path, roles: ChainRoles = ANTIBODY_ROLES) -> set[tuple[str, int]]:
    """Receptor residues (chain, sequence index) that contact the ligand."""
    pairs, _ = _interface(load(path), roles)
    return {(chain, index) for chain, index, _ in pairs}


def interface_agreement(
    reference: Path, other: Path, roles: ChainRoles = ANTIBODY_ROLES
) -> float:
    """Fraction of the reference prediction's contacts that the other prediction reproduces."""
    first, _ = _interface(load(reference), roles)
    second, _ = _interface(load(other), roles)
    return round(len(first & second) / max(1, len(first)), 3)
