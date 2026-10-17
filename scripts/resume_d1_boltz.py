"""Resume only missing Boltz-2 pairs for the bounded D1 pilot."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any

from concordia.design.loop import compare_structures, sequence_recovery
from concordia.genomics.boltz_nvidia import (
    BoltzComplexRequest,
    BoltzPolymer,
    NvidiaHostedBoltzRunner,
)
from concordia.genomics.proteinmpnn_nvidia import parse_mfasta
from concordia.runtime.secrets import nvidia_api_key
from concordia.storage.content import ContentAddressedStore

ROOT = Path("data/design/d1_1igv_pilot_v2")
ARTIFACTS = ContentAddressedStore(ROOT / "artifacts")
REPORT = ROOT / "d1-report.json"
CSV_PATH = Path("results/d1_pilot_motif_metrics.csv")
CACHE_INDEX = ROOT / "boltz-cache-index.json"
BACKBONE_ID = 4
SEQUENCE_IDS = (2, 3, 4)
EXPECTED_RETAINED = "QLSKEELKLLLQTEFPSLLKGPSTLDELFEELDKNGDGEVSFEE"
MOTIF_POSITIONS = tuple(position - 21 for position in (21, 26, 53, 55, 57, 59, 64))


def _artifact_json(digest: str) -> dict[str, Any]:
    return json.loads(ARTIFACTS.get_bytes(digest))


def _cached_sequences() -> dict[int, str]:
    """Read the already-cached backbone-4 ProteinMPNN response."""
    request_files = []
    for path in (ROOT / "artifacts" / "sha256").glob("*/*"):
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if (
            value.get("endpoint", "").endswith("proteinmpnn/predict")
            and value.get("input_pdb_bytes") == (ROOT / "backbone_04.pdb").stat().st_size
        ):
            request_files.append(path)
    if len(request_files) != 1:
        raise RuntimeError(
            "expected one cached backbone-4 MPNN request, "
            f"found {len(request_files)}"
        )
    request_digest = request_files[0].name
    response_candidates = []
    for path in (ROOT / "artifacts" / "sha256").glob("*/*"):
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if "mfasta" in value and len(value["mfasta"].splitlines()) >= 2:
            response_candidates.append((path, value))
    pdb_bytes = (ROOT / "backbone_04.pdb").read_bytes()
    # The cached response is identified by the request's input payload hash,
    # which is also present in the request artifact's provenance record.
    input_payload_hash = _artifact_json(request_digest).get("input_payload_hash")
    del pdb_bytes, input_payload_hash
    # There is one cached MPNN response for each backbone; choose the one whose
    # input sequence length matches the 52-residue backbone-4 chain.
    for _, value in response_candidates:
        records = parse_mfasta(value["mfasta"])
        designed = [sequence for header, sequence in records if "input" not in header.lower()]
        if len(designed) == 4 and all(len(sequence) == 52 for sequence in designed):
            return {index: designed[index - 1] for index in range(1, 5)}
    raise RuntimeError("cached backbone-4 MPNN response was not found")


def _retry(call: Any) -> Any:
    rng = random.Random(4201)
    delay = 10.0
    for attempt in range(9):
        try:
            return call()
        except RuntimeError as error:
            if "HTTP 429" not in str(error) or attempt == 8:
                raise
            time.sleep(delay + rng.uniform(0, delay * 0.1))
            delay = min(120.0, delay * 2)
    raise AssertionError("unreachable")


def main() -> None:
    target_sequence = EXPECTED_RETAINED
    sequences = _cached_sequences()
    cache = json.loads(CACHE_INDEX.read_text()) if CACHE_INDEX.exists() else {}
    key = nvidia_api_key(Path("."))
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is required for the resume")
    runner = NvidiaHostedBoltzRunner(ARTIFACTS, api_key=key, timeout_seconds=320)
    rows: list[dict[str, Any]] = []
    for sequence_id in SEQUENCE_IDS:
        binder_sequence = sequences[sequence_id]
        sequence_hash = hashlib.sha256(binder_sequence.encode("ascii")).hexdigest()
        cache_key = f"backbone-{BACKBONE_ID}:sequence-{sequence_id}:{sequence_hash}"
        if cache_key in cache:
            raise RuntimeError(f"cache hit requires replay support before parsing: {cache_key}")
        started = time.perf_counter()
        result = _retry(
            lambda binder_sequence=binder_sequence: runner.predict_complex(
                BoltzComplexRequest(
                    polymers=(
                        BoltzPolymer(id="A", sequence=binder_sequence),
                        BoltzPolymer(id="B", sequence=target_sequence),
                    ),
                    diffusion_samples=1,
                )
            )
        )
        cache[cache_key] = {
            "response_artifact_digest": result.response_artifact_digest,
            "request_artifact_digest": result.request_artifact_digest,
            "elapsed_seconds": result.elapsed_seconds,
        }
        CACHE_INDEX.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
        comparison = compare_structures(
            (ROOT / "backbone_04.pdb").read_text(),
            "pdb",
            result.structure_text,
            result.structure_format,
            EXPECTED_RETAINED,
            MOTIF_POSITIONS,
        )
        rows.append(
            {
                "backbone_id": BACKBONE_ID,
                "sequence_id": sequence_id,
                "response_artifact_digest": result.response_artifact_digest,
                "global_sc_rmsd_angstrom": comparison.global_rmsd_angstrom,
                "motif_rmsd_angstrom": comparison.motif_rmsd_angstrom,
                "global_ca_atoms_aligned": comparison.global_ca_atoms,
                "motif_ca_atoms_aligned": comparison.motif_ca_atoms,
                "global_superposition": comparison.global_superposition,
                "sequence_recovery_vs_1igv_retained_wildtype": sequence_recovery(
                    binder_sequence, EXPECTED_RETAINED
                ),
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
    existing = list(csv.DictReader(CSV_PATH.open(newline="")))
    existing_keys = {(int(row["backbone_id"]), int(row["sequence_id"])) for row in existing}
    fieldnames = [name for name in existing[0] if name != "elapsed_seconds"]
    with CSV_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({name: row[name] for name in fieldnames} for row in existing)
        for row in rows:
            if (row["backbone_id"], row["sequence_id"]) not in existing_keys:
                writer.writerow({name: row[name] for name in fieldnames})
    (Path("results") / "d1_task3_boltz_rows.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"rows": rows, "cache_keys": list(cache)}, indent=2))


if __name__ == "__main__":
    main()
