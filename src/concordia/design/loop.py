"""Deterministic policy and geometry helpers for the D1 design loop.

This module deliberately does not infer biological properties.  It only checks
the hard motif constraint, measures structural self-consistency, and renders a
scope-limited computational statement.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from io import StringIO
from typing import Any

import numpy as np
from Bio.Align import PairwiseAligner
from Bio.PDB import MMCIFParser, PDBParser
from Bio.PDB.Structure import Structure

D1_SCOPE_STATEMENT = (
    "A passing design means only that RFdiffusion, ProteinMPNN, and Boltz-2 "
    "were computationally self-consistent at the pre-registered RMSD thresholds. "
    "It does not show folding, stability, expression, binding, function, or "
    "biological success. pLDDT, pTM, and scRMSD are not biological-property evidence."
)


@dataclass(frozen=True)
class DesignRefusal:
    """A structured refusal that cannot be mistaken for a warning."""

    trigger: str
    evidence: dict[str, Any]
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "refused": True,
            "trigger": self.trigger,
            "evidence": self.evidence,
            "message": self.message,
        }


@dataclass(frozen=True)
class StructureComparison:
    """Design-chain and motif CA RMSDs measured in one global frame."""

    global_rmsd_angstrom: float
    motif_rmsd_angstrom: float
    global_ca_atoms: int
    motif_ca_atoms: int
    global_superposition: str


def motif_refusal(
    *,
    sequence: str,
    motif_positions: tuple[int, ...],
    motif_letters: str,
    accession: str,
    feature_type: str,
) -> DesignRefusal | None:
    """Refuse a sequence that changes any hard-protected motif residue."""

    violations: list[dict[str, Any]] = []
    for position, expected in zip(motif_positions, motif_letters, strict=True):
        index = position - 1
        observed = sequence[index] if 0 <= index < len(sequence) else None
        if observed != expected:
            violations.append(
                {
                    "local_position": position,
                    "expected": expected,
                    "observed": observed,
                    "accession": accession,
                    "feature_type": feature_type,
                }
            )
    if not violations:
        return None
    return DesignRefusal(
        trigger="HARD_PROTECTED_MOTIF_MUTATION",
        evidence={"violations": violations, "mutation_count": len(violations)},
        message="The design changes a UniProt-curated hard-protected residue.",
    )


def render_scope_statement() -> str:
    """Return the only biological-scope statement allowed for D1 output."""

    return D1_SCOPE_STATEMENT


def load_structure(text: str, structure_format: str, structure_id: str) -> Structure:
    """Parse PDB or mmCIF text without using model confidence as evidence."""

    if structure_format.lower() in {"cif", "mmcif"} or text.lstrip().startswith("data_"):
        return MMCIFParser(QUIET=True).get_structure(structure_id, StringIO(text))
    return PDBParser(QUIET=True).get_structure(structure_id, StringIO(text))


def chain_sequence(chain: Any) -> str:
    """Return a standard-residue sequence for a Bio.PDB chain."""

    mapping = {
        "ALA": "A",
        "ARG": "R",
        "ASN": "N",
        "ASP": "D",
        "CYS": "C",
        "GLN": "Q",
        "GLU": "E",
        "GLY": "G",
        "HIS": "H",
        "ILE": "I",
        "LEU": "L",
        "LYS": "K",
        "MET": "M",
        "PHE": "F",
        "PRO": "P",
        "SER": "S",
        "THR": "T",
        "TRP": "W",
        "TYR": "Y",
        "VAL": "V",
    }
    return "".join(mapping.get(residue.resname, "X") for residue in chain if residue.id[0] == " ")


def find_retained_target(
    structure: Structure, expected_sequence: str
) -> tuple[Any, tuple[int, ...]]:
    """Find the unique output chain containing the retained target region."""

    matches: list[tuple[Any, tuple[int, ...]]] = []
    for model in structure:
        for chain in model:
            sequence = chain_sequence(chain)
            if expected_sequence in sequence:
                start = sequence.index(expected_sequence)
                matches.append((chain, tuple(range(start, start + len(expected_sequence)))))
    if len(matches) != 1:
        raise ValueError(
            f"retained target sequence must occur exactly once, found {len(matches)} matches"
        )
    return matches[0]


def _ca_atoms(chain: Any, indices: tuple[int, ...] | None = None) -> list[Any]:
    residues = [residue for residue in chain if residue.id[0] == " " and "CA" in residue]
    if indices is None:
        return [residue["CA"] for residue in residues]
    return [residues[index]["CA"] for index in indices if index < len(residues)]


def _aligned_indices(first: str, second: str) -> tuple[tuple[int, int], ...]:
    aligner = PairwiseAligner()
    aligner.mode = "global"
    alignments = aligner.align(first, second)
    if not alignments:
        return ()
    alignment = alignments[0]
    pairs: list[tuple[int, int]] = []
    first_index = second_index = 0
    for first_block, second_block in zip(*alignment.aligned, strict=True):
        while first_index < first_block[0] or second_index < second_block[0]:
            if first_index < first_block[0]:
                first_index += 1
            if second_index < second_block[0]:
                second_index += 1
        for _ in range(first_block[1] - first_block[0]):
            pairs.append((first_index, second_index))
            first_index += 1
            second_index += 1
    return tuple(pairs)


def _superpose(
    first: np.ndarray[Any, Any], second: np.ndarray[Any, Any]
) -> tuple[
    float,
    np.ndarray[Any, Any],
    np.ndarray[Any, Any],
    np.ndarray[Any, Any],
    np.ndarray[Any, Any],
]:
    if len(first) != len(second) or len(first) < 3:
        raise ValueError("at least three aligned CA atoms are required for RMSD")
    first_center = first.mean(axis=0)
    second_center = second.mean(axis=0)
    centered_first = first - first_center
    centered_second = second - second_center
    covariance = centered_first.T @ centered_second
    left, _, right = np.linalg.svd(covariance)
    determinant = np.linalg.det(right.T @ left.T)
    rotation = right.T @ np.diag([1.0, 1.0, determinant]) @ left.T
    transformed = centered_first @ rotation
    rmsd = float(math.sqrt(np.mean(np.sum((transformed - centered_second) ** 2, axis=1))))
    return rmsd, transformed, rotation, first_center, second_center


def compare_structures(
    backbone_text: str,
    backbone_format: str,
    refold_text: str,
    refold_format: str,
    retained_sequence: str,
    motif_indices: tuple[int, ...],
) -> StructureComparison:
    """Compare the generated chain and motif in the generated-chain frame."""

    backbone = load_structure(backbone_text, backbone_format, "backbone")
    refold = load_structure(refold_text, refold_format, "refold")
    backbone_target, backbone_target_indices = find_retained_target(backbone, retained_sequence)
    refold_target, refold_target_indices = find_retained_target(refold, retained_sequence)
    backbone_generated = [chain for chain in backbone[0] if chain.id != backbone_target.id]
    refold_generated = [chain for chain in refold[0] if chain.id != refold_target.id]
    if len(backbone_generated) != 1 or len(refold_generated) != 1:
        raise ValueError("expected exactly one generated chain in each structure")
    backbone_generated_chain = backbone_generated[0]
    refold_generated_chain = refold_generated[0]
    backbone_sequence = chain_sequence(backbone_generated_chain)
    refold_sequence = chain_sequence(refold_generated_chain)
    if len(backbone_sequence) != len(refold_sequence):
        raise ValueError(
            "generated-chain length mismatch: "
            f"RFdiffusion={len(backbone_sequence)}, Boltz-2={len(refold_sequence)}"
        )
    pairs = _aligned_indices(backbone_sequence, refold_sequence)
    backbone_atoms = _ca_atoms(backbone_generated_chain)
    refold_atoms = _ca_atoms(refold_generated_chain)
    if not pairs:
        raise ValueError("generated-chain sequences did not align")
    first = np.asarray([backbone_atoms[i].coord for i, _ in pairs], dtype=np.float64)
    second = np.asarray([refold_atoms[j].coord for _, j in pairs], dtype=np.float64)
    global_rmsd, _, rotation, first_center, second_center = _superpose(first, second)

    target_backbone_atoms = _ca_atoms(backbone_target)
    target_refold_atoms = _ca_atoms(refold_target)
    motif_first = np.asarray(
        [target_backbone_atoms[backbone_target_indices[index]].coord for index in motif_indices],
        dtype=np.float64,
    )
    motif_second = np.asarray(
        [target_refold_atoms[refold_target_indices[index]].coord for index in motif_indices],
        dtype=np.float64,
    )
    # Motif RMSD uses the transform established by the global generated-chain fit.
    first_center = first.mean(axis=0)
    motif_transformed = (motif_first - first_center) @ rotation + second_center
    motif_rmsd = float(
        math.sqrt(np.mean(np.sum((motif_transformed - motif_second) ** 2, axis=1)))
    )
    return StructureComparison(
        global_rmsd_angstrom=global_rmsd,
        motif_rmsd_angstrom=motif_rmsd,
        global_ca_atoms=len(first),
        motif_ca_atoms=len(motif_indices),
        global_superposition="RFdiffusion generated chain A to Boltz-2 generated chain A",
    )


def sequence_recovery(sequence: str, baseline: str) -> float:
    """Return aligned identity against an explicitly named sequence baseline."""

    pairs = _aligned_indices(sequence, baseline)
    if not pairs:
        raise ValueError("sequences did not align for recovery")
    matches = sum(sequence[first] == baseline[second] for first, second in pairs)
    return float(matches / len(pairs))


def fixed_positions_jsonl(
    chain_id: str, positions: tuple[int, ...]
) -> str:
    """Create the schema-required ProteinMPNN fixed-position JSON string."""

    payload = {"input": {chain_id: list(positions)}}
    return json.dumps(payload, separators=(",", ":"))
