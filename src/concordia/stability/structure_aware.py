"""Local structure-aware stability adapters and deterministic safety gates."""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from concordia.stability.contracts import DestabilizingDDG, StabilityDDG, from_destabilizing


@dataclass(frozen=True)
class StructureMutation:
    variant_id: str
    position: int
    wildtype: str
    mutant: str
    mutation_count: int = 1


def should_refold(
    *,
    structure_exists: bool,
    mutation_count: int = 1,
    is_indel: bool = False,
    concerns_interface: bool = False,
) -> bool:
    """Deterministic refold gate; single substitutions never invoke a connector."""
    return not structure_exists or mutation_count > 1 or is_indel or concerns_interface


def proline_phi_rejection(
    pdb_path: Path, mutation: StructureMutation, *, lower: float = -90.0, upper: float = -40.0
) -> dict[str, Any] | None:
    """Reject a proline substitution when the fixed backbone cannot host its ring."""
    if mutation.mutant != "P":
        return None
    from Bio.PDB.PDBParser import PDBParser as _PDBParser
    from Bio.PDB.vectors import calc_dihedral as _calc_dihedral

    parser_cls: Any = _PDBParser
    calc_dihedral: Any = _calc_dihedral
    structure = parser_cls(QUIET=True).get_structure("phi", str(pdb_path))[0]
    residues = [res for res in structure.get_residues() if res.id[0] == " "]
    index = mutation.position - 1
    if index <= 0 or index >= len(residues) - 1:
        return {
            "code": "PROLINE_PHI_UNAVAILABLE",
            "position": mutation.position,
        }
    residue = residues[index]
    previous = residues[index - 1]
    if not all(atom in residue for atom in ("N", "CA", "C")) or "C" not in previous:
        return {"code": "PROLINE_PHI_UNAVAILABLE", "position": mutation.position}
    phi = math.degrees(
        float(
            calc_dihedral(
                previous["C"].get_vector(),
                residue["N"].get_vector(),
                residue["CA"].get_vector(),
                residue["C"].get_vector(),
            )
        )
    )
    if not lower <= phi <= upper:
        return {
            "code": "PROLINE_PHI_OUT_OF_RANGE",
            "position": mutation.position,
            "phi_degrees": phi,
            "allowed_range": [lower, upper],
        }
    return None


def _backbone_snapshot(path: Path) -> dict[tuple[str, int, str], tuple[float, float, float]]:
    from Bio.PDB.PDBParser import PDBParser as _PDBParser

    snapshot: dict[tuple[str, int, str], tuple[float, float, float]] = {}
    parser_cls: Any = _PDBParser
    structure = parser_cls(QUIET=True).get_structure("snapshot", str(path))[0]
    for chain in structure:
        for residue in chain:
            if residue.id[0] != " ":
                continue
            for atom_name in ("N", "CA", "C", "O"):
                if atom_name in residue:
                    coords = residue[atom_name].coord
                    snapshot[(chain.id, residue.id[1], atom_name)] = (
                        float(coords[0]),
                        float(coords[1]),
                        float(coords[2]),
                    )
    return snapshot


def compare_backbone(input_pdb: Path, output_pdb: Path) -> dict[str, Any]:
    before = _backbone_snapshot(input_pdb)
    after = _backbone_snapshot(output_pdb)
    keys = sorted(set(before) | set(after))
    mismatches = [key for key in keys if before.get(key) != after.get(key)]
    return {
        "backbone_atoms": len(before),
        "backbone_atoms_byte_identical": not mismatches,
        "backbone_mismatches": [str(key) for key in mismatches[:10]],
    }


def glycine_deletion(input_pdb: Path, output_pdb: Path, position: int) -> dict[str, Any]:
    """Represent A->G-style side-chain removal without invoking a packer."""
    from Bio.PDB.PDBIO import PDBIO as _PDBIO
    from Bio.PDB.PDBParser import PDBParser as _PDBParser

    parser_cls: Any = _PDBParser
    io_cls: Any = _PDBIO
    structure = parser_cls(QUIET=True).get_structure("glycine", str(input_pdb))
    residues = [residue for residue in structure[0].get_residues() if residue.id[0] == " "]
    residue = residues[position - 1]
    residue.resname = "GLY"
    for atom in list(residue):
        if atom.get_name() not in {"N", "CA", "C", "O"}:
            residue.detach_child(atom.id)
    io = io_cls()
    io.set_structure(structure)
    io.save(str(output_pdb))
    return {
        "backend": "deterministic_glycine_deletion",
        "removed_side_chain": True,
        "backbone": compare_backbone(input_pdb, output_pdb),
    }


class PIPPackLocalAdapter:
    """CPU PIPPack adapter; imports the pinned checkout only when invoked."""

    def __init__(self, repository: Path, weights: Path, *, seed: int = 42) -> None:
        self.repository = repository
        self.weights = weights
        self.seed = seed
        self._model: Any | None = None
        self._config: Any | None = None

    def _load(self) -> tuple[Any, Any]:
        if self._model is not None and self._config is not None:
            return self._model, self._config
        import sys

        sys.path.insert(0, str(self.repository))
        import hydra
        import lightning
        import torch
        from data.protein import from_pdb_file
        from data.top2018_dataset import transform_structure
        from model.resampling import resample_loop
        from utils.train_utils import load_checkpoint

        del from_pdb_file, resample_loop, transform_structure
        with open(self.weights / "pippack_model_1_config.pickle", "rb") as handle:
            import pickle

            exp_cfg = pickle.load(handle)
        model: Any = hydra.utils.instantiate(exp_cfg.model).to("cpu")
        load_checkpoint(str(self.weights / "pippack_model_1_ckpt.pt"), model)
        model.eval()
        lightning.seed_everything(self.seed, workers=True)
        self._model, self._config = model, exp_cfg
        del torch
        return model, exp_cfg

    def repack(
        self,
        input_pdb: Path,
        sequence: str,
        output_pdb: Path,
        mutation_position: int | None = None,
    ) -> dict[str, Any]:
        import sys

        sys.path.insert(0, str(self.repository))
        import torch
        from data.protein import from_pdb_file
        from data.top2018_dataset import collate_fn, transform_structure
        from inference import pdbs_from_prediction, replace_protein_sequence, sample_epoch

        model, config = self._load()
        protein = vars(from_pdb_file(str(input_pdb), mse_to_met=True))
        replaced = replace_protein_sequence(
            protein, input_pdb.stem, [[sequence]]
        )[0][1]
        replaced = transform_structure(
            replaced, config.model.n_chi_bins, sc_d_mask_from_seq=True
        )
        batch = collate_fn([replaced])
        with torch.no_grad():
            result = sample_epoch(model, batch, 0.0, torch.device("cpu"), n_recycle=3)
        output_pdb.write_text(pdbs_from_prediction(result)[0], encoding="utf-8")
        moved_nonmutant = _count_nonmutant_sidechain_changes(
            input_pdb, output_pdb, sequence, mutation_position
        )
        return {
            "backend": "PIPPack",
            "seed": self.seed,
            "temperature": 0.0,
            "context_aware_repacking": True,
            "non_mutant_side_chains_moved": moved_nonmutant,
            "backbone": compare_backbone(input_pdb, output_pdb),
        }


def _count_nonmutant_sidechain_changes(
    input_pdb: Path, output_pdb: Path, sequence: str, mutation_position: int | None
) -> int:
    """Count residue-sidechain coordinate changes, excluding the requested site."""
    from Bio.PDB.PDBParser import PDBParser as _PDBParser

    parser_cls: Any = _PDBParser
    before = parser_cls(QUIET=True).get_structure("before", str(input_pdb))[0]
    after = parser_cls(QUIET=True).get_structure("after", str(output_pdb))[0]
    changed = 0
    for b_chain, a_chain in zip(before, after, strict=True):
        for b_res, a_res in zip(
            [r for r in b_chain if r.id[0] == " "],
            [r for r in a_chain if r.id[0] == " "],
            strict=True,
        ):
            if mutation_position is not None and b_res.id[1] == mutation_position:
                continue
            sidechain_atoms = (
                {atom.get_name() for atom in b_res}
                & {atom.get_name() for atom in a_res}
            ) - {"N", "CA", "C", "O"}
            if any(
                tuple(float(x) for x in b_res[name].coord)
                != tuple(float(x) for x in a_res[name].coord)
                for name in sidechain_atoms
            ):
                changed += 1
    return changed


def pymol_fallback(
    input_pdb: Path, output_pdb: Path, mutation: StructureMutation
) -> dict[str, Any]:
    executable = shutil.which("pymol")
    if executable is None:
        raise RuntimeError("PIPPack failed and pymol-open-source is not installed")
    script = (
        f"load {input_pdb}, obj; wizard mutagenesis; refresh_wizard; "
        f"get_wizard().set_mode('{mutation.mutant}'); "
        f"get_wizard().do_select('chain A and resi {mutation.position}'); "
        "get_wizard().apply(); save %s, obj; quit" % output_pdb
    )
    subprocess.run([executable, "-cq"], input=script, text=True, check=True)
    return {"backend": "pymol-open-source", "deterministic_rotamer": "wizard-default"}


def from_thermompnn(value: float) -> StabilityDDG:
    """Convert ThermoMPNN's positive-is-destabilizing output at the boundary."""
    return from_destabilizing(DestabilizingDDG(float(value)))


__all__ = [
    "PIPPackLocalAdapter",
    "StructureMutation",
    "compare_backbone",
    "from_thermompnn",
    "glycine_deletion",
    "proline_phi_rejection",
    "pymol_fallback",
    "should_refold",
]
