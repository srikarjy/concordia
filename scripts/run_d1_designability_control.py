"""Run the bounded 1PGB designability control for the D1 pilot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from concordia.design.loop import chain_sequence, load_structure
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzRunner
from concordia.genomics.proteinmpnn_nvidia import (
    NvidiaHostedProteinMpnnRunner,
    ProteinMpnnRequest,
    parse_mfasta,
)
from concordia.runtime.secrets import nvidia_api_key
from concordia.storage.content import ContentAddressedStore

ROOT = Path("data/design/d1_control")
PDB = ROOT / "1PGB.pdb"
ARTIFACTS = ContentAddressedStore(ROOT / "artifacts")
INDEX = ROOT / "cache-index.json"


def _ca_coordinates(text: str, chain_id: str) -> np.ndarray:
    structure = load_structure(text, "pdb", f"control-{chain_id}")
    chain = structure[0][chain_id]
    points = [residue["CA"].coord for residue in chain if "CA" in residue]
    return np.asarray(points, dtype=np.float64)


def _rmsd(native: np.ndarray, predicted: np.ndarray) -> tuple[float, int]:
    if len(native) != len(predicted):
        raise ValueError(f"control structure length mismatch: {len(native)} != {len(predicted)}")
    first_center = native.mean(axis=0)
    second_center = predicted.mean(axis=0)
    first = native - first_center
    second = predicted - second_center
    covariance = first.T @ second
    left, _, right_transpose = np.linalg.svd(covariance)
    rotation = left @ right_transpose
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right_transpose
    transformed = first @ rotation
    return float(np.sqrt(np.mean(np.sum((transformed - second) ** 2, axis=1)))), len(native)


def _load_or_call_mpnn(key: str, pdb_text: str) -> tuple[list[str], dict[str, Any]]:
    cache = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    cached = cache.get("proteinmpnn")
    if cached:
        payload = json.loads(ARTIFACTS.get_bytes(cached["response_artifact_digest"]))
        return (
            [
                record[1]
                for record in parse_mfasta(payload["mfasta"])
                if "input" not in record[0].lower()
            ],
            cached,
        )
    runner = NvidiaHostedProteinMpnnRunner(ARTIFACTS, api_key=key, timeout_seconds=300)
    result = runner.design(
        ProteinMpnnRequest(
            input_pdb=pdb_text,
            design_chains=("A",),
            num_sequences=2,
            sampling_temperature=0.1,
            random_seed=4201,
        )
    )
    metadata = {
        "request_artifact_digest": result.request_artifact_digest,
        "response_artifact_digest": result.response_artifact_digest,
    }
    cache["proteinmpnn"] = metadata
    INDEX.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    return [item.sequence for item in result.designed_sequences], metadata


def main() -> None:
    key = nvidia_api_key(Path("."))
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is required for the control")
    pdb_text = PDB.read_text()
    native_structure = load_structure(pdb_text, "pdb", "1PGB-native")
    native_sequence = chain_sequence(native_structure[0]["A"])
    sequences, mpnn_cache = _load_or_call_mpnn(key, pdb_text)
    if len(sequences) < 2:
        raise RuntimeError("ProteinMPNN returned fewer than two control sequences")
    runner = NvidiaHostedBoltzRunner(ARTIFACTS, api_key=key, timeout_seconds=320)
    cache = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    rows: list[dict[str, Any]] = []
    native_ca = _ca_coordinates(pdb_text, "A")
    for index, sequence in enumerate(sequences[:2], start=1):
        sequence_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        cache_key = f"boltz-sequence-{index}:{sequence_hash}"
        if cache_key in cache:
            response_digest = cache[cache_key]["response_artifact_digest"]
            payload = json.loads(ARTIFACTS.get_bytes(response_digest))
            structure_text = payload["structure"]
            structure_format = payload.get("structure_format", "pdb")
            elapsed = cache[cache_key]["elapsed_seconds"]
        else:
            result = runner.predict(sequence)
            cache[cache_key] = {
                "request_artifact_digest": result.request_artifact_digest,
                "response_artifact_digest": result.response_artifact_digest,
                "elapsed_seconds": result.elapsed_seconds,
            }
            INDEX.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
            response_digest = result.response_artifact_digest
            structure_text = result.structure_text
            structure_format = result.structure_format
            elapsed = result.elapsed_seconds
        del structure_format
        predicted_ca = _ca_coordinates(structure_text, "A")
        rmsd, atom_count = _rmsd(native_ca, predicted_ca)
        rows.append(
            {
                "sequence_id": index,
                "sequence": sequence,
                "sequence_length": len(sequence),
                "native_sequence_length": len(native_sequence),
                "native_ca_atoms": atom_count,
                "sc_rmsd_angstrom": rmsd,
                "response_artifact_digest": response_digest,
                "elapsed_seconds": elapsed,
            }
        )
    output = {
        "pdb": str(PDB),
        "pdb_id": "1PGB",
        "chain": "A",
        "native_sequence_length": len(native_sequence),
        "proteinmpnn": mpnn_cache,
        "rows": rows,
        "interpretation": (
            "under 2 A supports a working computational pipeline; above 5 A makes "
            "the pipeline settings or chain handling suspect"
        ),
    }
    (ROOT / "control-report.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
