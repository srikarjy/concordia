"""Fail-closed ThermoMPNN feasibility records.

This module deliberately supports only the preregistered single-chain,
single-substitution pilot.  It records unavailable prerequisites as evidence;
it never replaces fresh model inference with Concordia's frozen ranker.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
PINNED_COMMIT = "370f76ec62bd929f7425e311d8df04a0d094990f"
PINNED_WEIGHTS_SHA256 = "af449118ccfb4e34971d802321907ed82a8a035ae80f055bf8fc56009a4a838a"
CHECKPOINT_RELATIVE_PATH = Path("models/thermoMPNN_default.pt")


class PilotRefusal(ValueError):
    """The input is outside the intentionally small feasibility scope."""


@dataclass(frozen=True)
class PilotRequest:
    structure_path: Path
    manifest_path: Path
    chain_id: str
    position: int
    wildtype: str
    mutant: str
    variant_id: str
    seed: int = 20261019
    dtype: Literal["float32"] = "float32"
    device: Literal["cpu"] = "cpu"
    wall_clock_limit_seconds: int = 20 * 60
    memory_limit_bytes: int = 8 * 1024**3

    def __post_init__(self) -> None:
        if len(self.chain_id) != 1:
            raise PilotRefusal("scope supports exactly one one-character chain identifier")
        if self.position < 1:
            raise PilotRefusal("mutation position must be one-based and positive")
        if self.wildtype not in CANONICAL_AMINO_ACIDS or self.mutant not in CANONICAL_AMINO_ACIDS:
            raise PilotRefusal("wildtype and mutant must be canonical amino acids")
        if self.wildtype == self.mutant:
            raise PilotRefusal("wildtype and mutant must differ")
        if self.device != "cpu" or self.dtype != "float32":
            raise PilotRefusal("the feasibility pilot is pinned to CPU float32")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _structure_sequence(request: PilotRequest) -> tuple[str, list[dict[str, Any]]]:
    """Read a uniquely mapped canonical chain without inspecting assay labels."""
    from Bio.Data.IUPACData import protein_letters_3to1
    from Bio.PDB import PDBParser

    structure = PDBParser(QUIET=True).get_structure("feasibility", str(request.structure_path))
    models = list(structure)
    if len(models) != 1:
        raise PilotRefusal("scope requires exactly one structure model")
    chains = [chain for chain in models[0] if chain.id == request.chain_id]
    if len(chains) != 1:
        raise PilotRefusal(f"chain {request.chain_id!r} is missing or ambiguous")
    residues = [residue for residue in chains[0] if residue.id[0] == " "]
    if not residues:
        raise PilotRefusal("selected chain has no standard residues")
    sequence: list[str] = []
    mapping: list[dict[str, Any]] = []
    expected_resseq: int | None = None
    for index, residue in enumerate(residues, start=1):
        resseq, insertion_code = int(residue.id[1]), str(residue.id[2]).strip()
        if insertion_code:
            raise PilotRefusal("scope does not support insertion codes")
        if expected_resseq is not None and resseq != expected_resseq:
            raise PilotRefusal("scope requires a complete contiguous residue mapping")
        expected_resseq = resseq + 1
        name = residue.resname.title()
        amino_acid = protein_letters_3to1.get(name)
        if amino_acid not in CANONICAL_AMINO_ACIDS:
            raise PilotRefusal(f"unsupported residue {residue.resname!r} at {resseq}")
        if any(atom not in residue for atom in ("N", "CA", "C", "O")):
            raise PilotRefusal(f"missing backbone atom at residue {resseq}")
        sequence.append(amino_acid)
        mapping.append({"sequence_position": index, "residue_number": resseq, "insertion_code": ""})
    return "".join(sequence), mapping


def _repository_identity(root: Path | None) -> tuple[dict[str, Any], list[str]]:
    identity: dict[str, Any] = {"expected_commit": PINNED_COMMIT, "actual_commit": None}
    blockers: list[str] = []
    if root is None:
        return identity, ["ThermoMPNN source root was not provided"]
    if not root.is_dir():
        return identity, [f"ThermoMPNN source root does not exist: {root}"]
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        identity["actual_commit"] = completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        blockers.append("ThermoMPNN source root is not a readable Git checkout")
    if identity["actual_commit"] != PINNED_COMMIT:
        blockers.append("ThermoMPNN source commit does not match the pinned commit")
    return identity, blockers


def _checkpoint_identity(root: Path | None) -> tuple[dict[str, Any], list[str]]:
    identity: dict[str, Any] = {
        "expected_sha256": PINNED_WEIGHTS_SHA256,
        "actual_sha256": None,
        "relative_path": str(CHECKPOINT_RELATIVE_PATH),
    }
    if root is None:
        return identity, ["ThermoMPNN checkpoint cannot be located without a source root"]
    checkpoint = root / CHECKPOINT_RELATIVE_PATH
    if not checkpoint.is_file():
        return identity, [f"ThermoMPNN checkpoint is absent: {checkpoint}"]
    identity["actual_sha256"] = file_digest(checkpoint)
    if identity["actual_sha256"] != PINNED_WEIGHTS_SHA256:
        return identity, ["ThermoMPNN checkpoint digest does not match the pinned digest"]
    return identity, []


@dataclass(frozen=True)
class FeasibilityPilot:
    """Build a self-contained record before optional model execution begins."""

    request: PilotRequest
    thermompnn_root: Path | None = None

    def preflight(self) -> dict[str, Any]:
        if not self.request.structure_path.is_file():
            raise PilotRefusal(f"structure is absent: {self.request.structure_path}")
        if not self.request.manifest_path.is_file():
            raise PilotRefusal(f"manifest is absent: {self.request.manifest_path}")
        sequence, mapping = _structure_sequence(self.request)
        if self.request.position > len(sequence):
            raise PilotRefusal("mutation position lies outside mapped sequence")
        observed = sequence[self.request.position - 1]
        if observed != self.request.wildtype:
            raise PilotRefusal(
                f"wildtype mismatch at position {self.request.position}: structure has {observed}"
            )
        repository, repository_blockers = _repository_identity(self.thermompnn_root)
        checkpoint, checkpoint_blockers = _checkpoint_identity(self.thermompnn_root)
        return {
            "structure": {
                "path": str(self.request.structure_path),
                "sha256": file_digest(self.request.structure_path),
                "origin": "AlphaFold predicted structure; not experimental evidence",
                "chain_id": self.request.chain_id,
                "sequence": sequence,
                "mapping": mapping,
            },
            "source_manifest": {
                "path": str(self.request.manifest_path),
                "sha256": file_digest(self.request.manifest_path),
                "variant_id": self.request.variant_id,
            },
            "model": {"source": repository, "checkpoint": checkpoint},
            "blockers": repository_blockers + checkpoint_blockers,
        }


def build_feasibility_record(pilot: FeasibilityPilot) -> dict[str, Any]:
    """Return an immutable-style terminal record for the bounded pilot.

    Fresh model execution belongs after this preflight.  Until all pinned assets
    verify, recording ``unavailable`` is the only valid terminal result.
    """
    preflight = pilot.preflight()
    blockers = preflight["blockers"]
    return {
        "schema_version": 1,
        "investigation": "thermompnn_cpu_feasibility",
        "status": "unavailable" if blockers else "ready_for_bounded_execution",
        "terminal_reason": "; ".join(blockers) if blockers else None,
        "request": {
            **asdict(pilot.request),
            "structure_path": str(pilot.request.structure_path),
            "manifest_path": str(pilot.request.manifest_path),
        },
        "target": {
            "formula": "f = -raw ThermoMPNN ddG",
            "units": "kcal/mol",
            "direction": "higher values mean more stable",
            "raw_output": None,
            "converted_output": None,
        },
        "preflight": preflight,
        "execution": {
            "attempted": False,
            "ordinary_adapter_parity": "not_run",
            "embedding_injection_parity": "not_run",
            "gradient_check": "not_run",
            "integrated_gradients": "not_run",
            "context_substitution_diagnostic": "not_run",
        },
        "scientific_use_allowed": False,
        "limitations": [
            "This is a compute and mapping feasibility record, not predictor validation.",
            "No assay label was read by this feasibility record.",
            "Unavailable prerequisites do not establish a model execution or attribution result.",
        ],
    }


def replay_record(path: Path) -> dict[str, Any]:
    """Read a saved record only after verifying its adjacent SHA-256 sidecar."""
    sidecar = path.with_suffix(path.suffix + ".sha256")
    expected = sidecar.read_text(encoding="utf-8").strip()
    actual = file_digest(path)
    if expected != actual:
        raise ValueError("feasibility record digest does not match its sidecar")
    return json.loads(path.read_text(encoding="utf-8"))
