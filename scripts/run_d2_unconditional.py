"""Run the pre-registered unconditional RFdiffusion D2 loop."""

from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from concordia.design.loop import chain_sequence, load_structure, render_scope_statement
from concordia.events.sqlite import SQLiteEventLedger, request_digest
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzRunner
from concordia.genomics.proteinmpnn_nvidia import (
    NvidiaHostedProteinMpnnRunner,
    ProteinMpnnRequest,
    parse_mfasta,
)
from concordia.genomics.rfdiffusion_nvidia import (
    NvidiaHostedRFdiffusionRunner,
    RFdiffusionRequest,
)
from concordia.runtime.secrets import nvidia_api_key
from concordia.storage.content import ContentAddressedStore

MANIFEST = Path("data/manifests/design_d2_unconditional_v1.json")
OUTPUT = Path("data/design/d2_unconditional_v1")
SEQUENCE_BASELINE = "generated_backbone_chain_a"


def _ca_coordinates(text: str, structure_format: str = "pdb") -> np.ndarray[Any, Any]:
    structure = load_structure(text, structure_format, "d2")
    chains = list(structure[0])
    if len(chains) != 1:
        raise ValueError(f"expected one unconditional chain, found {len(chains)}")
    points = [residue["CA"].coord for residue in chains[0] if "CA" in residue]
    return np.asarray(points, dtype=np.float64)


def _rmsd(first: np.ndarray[Any, Any], second: np.ndarray[Any, Any]) -> float:
    if first.shape != second.shape or len(first) < 3:
        raise ValueError(f"unmatched CA coordinates: {first.shape} != {second.shape}")
    first_center = first.mean(axis=0)
    second_center = second.mean(axis=0)
    centered_first = first - first_center
    centered_second = second - second_center
    left, _, right_transpose = np.linalg.svd(centered_first.T @ centered_second)
    rotation = left @ right_transpose
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1
        rotation = left @ right_transpose
    transformed = centered_first @ rotation
    return float(np.sqrt(np.mean(np.sum((transformed - centered_second) ** 2, axis=1))))


def _retry(call: Any, counters: dict[str, int]) -> Any:
    rng = random.Random(5201 + counters["429"])
    delay = 10.0
    for attempt in range(9):
        try:
            return call()
        except RuntimeError as error:
            if "HTTP 429" not in str(error):
                raise
            counters["429"] += 1
            if attempt == 8:
                raise RuntimeError("D2 route remained rate-limited after eight retries") from error
            time.sleep(delay + rng.uniform(0.0, delay * 0.1))
            delay = min(120.0, delay * 2)
    raise AssertionError("unreachable")


def _append_event(
    ledger: SQLiteEventLedger, run_id: str, sequence: int, kind: str, payload: dict[str, Any]
) -> int:
    ledger.append(run_id, kind, payload, expected_sequence=sequence)
    return sequence + 1


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    if not manifest["created_without_campaign_calls"]:
        raise ValueError("D2 manifest was not frozen before generation")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = ContentAddressedStore(OUTPUT / "artifacts")
    ledger = SQLiteEventLedger(OUTPUT / "events.sqlite3")
    request_metadata = {"manifest": str(MANIFEST), "campaign": manifest["campaign"]}
    command_digest = request_digest(request_metadata)
    run_id = str(uuid.uuid4())
    ledger.create_run(
        run_id=run_id,
        idempotency_key=f"d2:{command_digest}",
        command_digest=command_digest,
        payload=request_metadata,
        event_id=str(uuid.uuid4()),
    )
    sequence_number = 1
    sequence_number = _append_event(
        ledger,
        run_id,
        sequence_number,
        "D2_PREREGISTERED",
        {"manifest": str(MANIFEST), "success_criterion": manifest["success_criterion"]},
    )
    key = nvidia_api_key(Path("."))
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is required for D2")
    rf = NvidiaHostedRFdiffusionRunner(artifacts, api_key=key, timeout_seconds=600)
    mpnn = NvidiaHostedProteinMpnnRunner(artifacts, api_key=key, timeout_seconds=300)
    boltz = NvidiaHostedBoltzRunner(artifacts, api_key=key, timeout_seconds=320)
    phase = manifest["generation"]
    seeds = tuple(int(seed) for seed in phase["rfdiffusion_seeds"])
    retry_counters = {"429": 0}
    total_latency = 0.0
    last_boltz_call: float | None = None
    rows: list[dict[str, Any]] = []
    backbone_summaries: list[dict[str, Any]] = []
    cache_index: dict[str, Any] = {}

    for backbone_id, seed in enumerate(seeds, start=1):
        rf_result = _retry(
            lambda seed=seed: rf.generate(
                RFdiffusionRequest(
                    target_pdb=None,
                    contigs=str(phase["contigs"]),
                    diffusion_steps=50,
                    random_seed=seed,
                )
            ),
            retry_counters,
        )
        total_latency += rf_result.elapsed_seconds
        backbone_path = OUTPUT / f"backbone_{backbone_id:02d}.pdb"
        backbone_path.write_text(rf_result.pdb_text)
        backbone_sequence = chain_sequence(load_structure(rf_result.pdb_text, "pdb", "d2")[0]["A"])
        backbone_hash = hashlib.sha256(backbone_sequence.encode("ascii")).hexdigest()
        cache_index[f"backbone-{backbone_id}:{backbone_hash}"] = {
            "rfdiffusion_response_artifact_digest": rf_result.response_artifact_digest,
            "rfdiffusion_request_artifact_digest": rf_result.request_artifact_digest,
        }
        mpnn_result = _retry(
            lambda pdb=rf_result.pdb_text: mpnn.design(
                ProteinMpnnRequest(
                    input_pdb=pdb,
                    design_chains=("A",),
                    num_sequences=int(phase["sequences_per_backbone"]),
                    sampling_temperature=float(phase["proteinmpnn_sampling_temperature"]),
                    random_seed=int(phase["proteinmpnn_seed"]),
                )
            ),
            retry_counters,
        )
        total_latency += mpnn_result.elapsed_seconds
        records = parse_mfasta(
            "\n".join(
                f">{item.header}\n{item.sequence}" for item in mpnn_result.designed_sequences
            )
        )
        designs = [record[1] for record in records if "input" not in record[0].lower()]
        if len(designs) < int(phase["sequences_per_backbone"]):
            raise RuntimeError(f"backbone {backbone_id} returned too few ProteinMPNN sequences")
        if len(set(designs[:4])) != 4:
            raise RuntimeError(f"backbone {backbone_id} did not produce four distinct sequences")
        cache_index[f"proteinmpnn-{backbone_id}:{backbone_hash}"] = {
            "response_artifact_digest": mpnn_result.response_artifact_digest,
            "request_artifact_digest": mpnn_result.request_artifact_digest,
        }
        backbone_rows: list[dict[str, Any]] = []
        for sequence_id, sequence in enumerate(designs[:4], start=1):
            if len(sequence) != len(backbone_sequence):
                raise RuntimeError(
                    f"backbone {backbone_id} sequence {sequence_id} length mismatch: "
                    f"{len(sequence)} != {len(backbone_sequence)}"
                )
            if last_boltz_call is not None:
                elapsed = time.monotonic() - last_boltz_call
                if elapsed < float(phase["inter_call_delay_seconds"]):
                    time.sleep(float(phase["inter_call_delay_seconds"]) - elapsed)
            last_boltz_call = time.monotonic()
            boltz_result = _retry(lambda sequence=sequence: boltz.predict(sequence), retry_counters)
            total_latency += boltz_result.elapsed_seconds
            prediction = _ca_coordinates(boltz_result.structure_text, boltz_result.structure_format)
            design = _ca_coordinates(rf_result.pdb_text)
            if design.shape != prediction.shape:
                raise RuntimeError(
                    f"Boltz length mismatch for backbone {backbone_id} sequence {sequence_id}: "
                    f"{design.shape[0]} != {prediction.shape[0]}"
                )
            rmsd = _rmsd(design, prediction)
            confidence = list(boltz_result.confidence_scores)
            row = {
                "backbone_id": backbone_id,
                "sequence_id": sequence_id,
                "sequence": sequence,
                "sequence_length": len(sequence),
                "sequence_recovery_baseline": SEQUENCE_BASELINE,
                "sequence_recovery": sum(
                    observed == expected
                    for observed, expected in zip(sequence, backbone_sequence, strict=True)
                ) / len(backbone_sequence),
                "global_sc_rmsd_angstrom": rmsd,
                "global_ca_atoms_aligned": int(design.shape[0]),
                "plddt_mean_reported": (
                    float(np.mean(confidence)) if confidence else None
                ),
                "ptm_reported": None,
                "passes": rmsd < float(manifest["success_criterion"]["global_sc_rmsd_angstrom_lt"]),
                "pLDDT_used_as_criterion": False,
                "pTM_used_as_criterion": False,
                "response_artifact_digest": boltz_result.response_artifact_digest,
                "elapsed_seconds": boltz_result.elapsed_seconds,
            }
            rows.append(row)
            backbone_rows.append(row)
            sequence_digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            cache_index[f"boltz-{backbone_id}-{sequence_id}:{sequence_digest}"] = {
                "response_artifact_digest": boltz_result.response_artifact_digest,
                "request_artifact_digest": boltz_result.request_artifact_digest,
            }
        backbone_summaries.append(
            {
                "backbone_id": backbone_id,
                "sequence_count": len({row["sequence"] for row in backbone_rows}),
                "sc_rmsd_count": len({row["global_sc_rmsd_angstrom"] for row in backbone_rows}),
            }
        )

    (OUTPUT / "cache-index.json").write_text(
        json.dumps(cache_index, indent=2, sort_keys=True) + "\n"
    )
    passing = [row for row in rows if row["passes"]]
    payload = {
        "manifest": manifest,
        "run_id": run_id,
        "rows": rows,
        "backbone_summaries": backbone_summaries,
        "hosted_calls": {
            "rfdiffusion": 4,
            "proteinmpnn": 4,
            "boltz2": 16,
            "rate_limit_429_count": retry_counters["429"],
            "total_latency_seconds": total_latency,
        },
        "fraction_passing": len(passing) / len(rows),
        "scope_statement": render_scope_statement(),
        "scientific_use_allowed": False,
    }
    report_digest = artifacts.put_json(payload)
    sequence_number = _append_event(
        ledger,
        run_id,
        sequence_number,
        "D2_COMPLETED",
        {"artifact_digest": report_digest, "hosted_calls": payload["hosted_calls"]},
    )
    payload["artifact_digest"] = report_digest
    payload["ledger_last_sequence"] = sequence_number - 1
    payload["ledger_chain"] = ledger.verify_chain(run_id).model_dump(mode="json")
    (OUTPUT / "d2-report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
