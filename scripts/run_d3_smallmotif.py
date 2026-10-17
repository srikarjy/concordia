"""Run the final bounded D3 small-contiguous-motif design campaign."""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from concordia.design.loop import (
    chain_sequence,
    compare_structures,
    find_retained_target,
    load_structure,
    sequence_recovery,
)
from concordia.events.sqlite import SQLiteEventLedger, request_digest
from concordia.genomics.boltz_nvidia import (
    BoltzComplexRequest,
    BoltzPolymer,
    NvidiaHostedBoltzRunner,
)
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

T = TypeVar("T")


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "pre_registered_before_generation":
        raise ValueError("D3 manifest is not preregistered")
    return manifest


def call_with_backoff(call: Callable[[], T], *, retries: int, initial: float, cap: float) -> T:
    delay = initial
    for attempt in range(retries + 1):
        try:
            return call()
        except RuntimeError as error:
            if "HTTP 429" not in str(error) or attempt == retries:
                raise
            time.sleep(delay + random.uniform(0, min(2.0, delay * 0.1)))
            delay = min(cap, delay * 2)
    raise AssertionError("unreachable")


def response_metrics(store: ContentAddressedStore, digest: str) -> dict[str, Any]:
    payload = json.loads(store.get_bytes(digest))
    scores = payload.get("confidence_scores")
    plddt = None
    if isinstance(scores, list) and scores:
        numeric = [float(value) for value in scores if isinstance(value, int | float)]
        if numeric:
            plddt = sum(numeric) / len(numeric)
    return {"pLDDT_reported": plddt, "pTM_reported": payload.get("ptm", payload.get("pTM"))}


def append_event(
    ledger: SQLiteEventLedger, run_id: str, seq: int, kind: str, payload: dict[str, Any]
) -> int:
    ledger.append(run_id, kind, payload, expected_sequence=seq)
    return seq + 1


def run(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    target = manifest["target"]
    target_pdb = Path(target["pdb_path"]).read_text(encoding="utf-8")
    retained = str(target["retained_sequence"])
    motif_indices = tuple(range(len(retained)))
    output_dir.mkdir(parents=True, exist_ok=True)
    store = ContentAddressedStore(output_dir / "artifacts")
    ledger = SQLiteEventLedger(output_dir / "events.sqlite3")
    run_id = str(uuid.uuid4())
    command = {"manifest": str(manifest_path), "campaign": manifest["campaign"]}
    command_hash = request_digest(command)
    ledger.create_run(
        run_id=run_id,
        idempotency_key=f"d3:{command_hash}",
        command_digest=command_hash,
        payload=command,
        event_id=str(uuid.uuid4()),
    )
    sequence_no = 1
    sequence_no = append_event(
        ledger,
        run_id,
        sequence_no,
        "D3_PREREGISTERED",
        {
            "manifest": str(manifest_path),
            "contig": target["contig"],
            "success_criterion": manifest["success_criterion"],
        },
    )
    key = nvidia_api_key(Path("."))
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is required for D3")
    rf = NvidiaHostedRFdiffusionRunner(store, api_key=key, timeout_seconds=320)
    mpnn = NvidiaHostedProteinMpnnRunner(store, api_key=key, timeout_seconds=320)
    boltz = NvidiaHostedBoltzRunner(store, api_key=key, timeout_seconds=360)
    settings = manifest["generation"]
    counts = {"rfdiffusion": 0, "proteinmpnn": 0, "boltz2": 0, "429": 0}
    rows: list[dict[str, Any]] = []
    backbones: list[dict[str, Any]] = []
    total_latency = 0.0
    last_boltz: float | None = None
    try:
        for backbone_id, seed in enumerate(settings["rfdiffusion_seeds"], start=1):
            rf_result = call_with_backoff(
                lambda seed=seed: rf.generate(
                    RFdiffusionRequest(
                        target_pdb=target_pdb,
                        contigs=target["contig"],
                        diffusion_steps=50,
                        random_seed=int(seed),
                    )
                ),
                retries=int(settings["rate_limit_max_retries"]),
                initial=float(settings["rate_limit_retry_initial_seconds"]),
                cap=float(settings["rate_limit_retry_cap_seconds"]),
            )
            counts["rfdiffusion"] += 1
            total_latency += rf_result.elapsed_seconds
            backbone_path = output_dir / f"backbone_{backbone_id:02d}.pdb"
            backbone_path.write_text(rf_result.pdb_text, encoding="utf-8")
            structure = load_structure(rf_result.pdb_text, "pdb", f"d3-backbone-{backbone_id}")
            retained_chain, _ = find_retained_target(structure, retained)
            generated = [chain for chain in structure[0] if chain.id != retained_chain.id]
            if len(generated) != 1:
                raise ValueError(f"backbone {backbone_id} does not have one generated chain")
            generated_chain = generated[0]
            generated_sequence = chain_sequence(generated_chain)
            if any(letter not in "ARNDCQEGHILKMFPSTWYV" for letter in generated_sequence):
                raise ValueError(f"backbone {backbone_id} contains non-standard residues")
            if retained not in chain_sequence(retained_chain):
                raise ValueError(f"backbone {backbone_id} lost retained motif")
            backbones.append(
                {
                    "backbone_id": backbone_id,
                    "path": str(backbone_path),
                    "generated_chain_id": generated_chain.id,
                    "generated_length": len(generated_sequence),
                    "retained_chain_id": retained_chain.id,
                    "retained_sequence": retained,
                    "motif_present": True,
                    "rf_request_artifact_digest": rf_result.request_artifact_digest,
                    "rf_response_artifact_digest": rf_result.response_artifact_digest,
                }
            )
            mpnn_result = call_with_backoff(
                lambda chain_id=generated_chain.id, pdb=rf_result.pdb_text: mpnn.design(
                    ProteinMpnnRequest(
                        input_pdb=pdb,
                        design_chains=(chain_id,),
                        num_sequences=int(settings["sequences_per_backbone"]),
                        sampling_temperature=float(settings["proteinmpnn_sampling_temperature"]),
                        random_seed=int(settings["proteinmpnn_seed"]),
                    )
                ),
                retries=int(settings["rate_limit_max_retries"]),
                initial=float(settings["rate_limit_retry_initial_seconds"]),
                cap=float(settings["rate_limit_retry_cap_seconds"]),
            )
            counts["proteinmpnn"] += 1
            total_latency += mpnn_result.elapsed_seconds
            records = parse_mfasta(
                "\n".join(
                    f">{item.header}\n{item.sequence}" for item in mpnn_result.designed_sequences
                )
            )
            designs = [record[1] for record in records if "input" not in record[0].lower()]
            if len(designs) < int(settings["sequences_per_backbone"]):
                raise ValueError(f"backbone {backbone_id} returned too few sequences")
            for sequence_id, design_sequence in enumerate(designs[:4], start=1):
                if len(design_sequence) != len(generated_sequence):
                    raise ValueError(
                        f"ProteinMPNN length mismatch on backbone {backbone_id}: "
                        f"{len(design_sequence)} != {len(generated_sequence)}"
                    )
                if last_boltz is not None:
                    wait = float(settings["inter_call_delay_seconds"]) - (
                        time.monotonic() - last_boltz
                    )
                    if wait > 0:
                        time.sleep(wait)
                last_boltz = time.monotonic()
                boltz_result = call_with_backoff(
                    lambda sequence=design_sequence: boltz.predict_complex(
                        BoltzComplexRequest(
                            polymers=(
                                BoltzPolymer(id="A", molecule_type="protein", sequence=sequence),
                                BoltzPolymer(id="B", molecule_type="protein", sequence=retained),
                            ),
                            diffusion_samples=1,
                        )
                    ),
                    retries=int(settings["rate_limit_max_retries"]),
                    initial=float(settings["rate_limit_retry_initial_seconds"]),
                    cap=float(settings["rate_limit_retry_cap_seconds"]),
                )
                counts["boltz2"] += 1
                total_latency += boltz_result.elapsed_seconds
                comparison = compare_structures(
                    rf_result.pdb_text,
                    "pdb",
                    boltz_result.structure_text,
                    boltz_result.structure_format,
                    retained,
                    motif_indices,
                )
                row = {
                    "backbone_id": backbone_id,
                    "sequence_id": sequence_id,
                    "sc_rmsd_angstrom": comparison.global_rmsd_angstrom,
                    "global_ca_atoms_aligned": comparison.global_ca_atoms,
                    "motif_rmsd_angstrom": comparison.motif_rmsd_angstrom,
                    "motif_ca_atoms_aligned": comparison.motif_ca_atoms,
                    "sequence_recovery_vs_generated_backbone": sequence_recovery(
                        design_sequence, generated_sequence
                    ),
                    "global_superposition": comparison.global_superposition,
                    **response_metrics(store, boltz_result.response_artifact_digest),
                    "passes": (
                        comparison.global_rmsd_angstrom
                        < float(manifest["success_criterion"]["global_sc_rmsd_angstrom_lt"])
                        and comparison.motif_rmsd_angstrom
                        < float(manifest["success_criterion"]["motif_rmsd_angstrom_lt"])
                    ),
                    "pLDDT_used_as_criterion": False,
                    "pTM_used_as_criterion": False,
                    "response_artifact_digest": boltz_result.response_artifact_digest,
                }
                rows.append(row)
    except RuntimeError as error:
        report = {
            "manifest": manifest,
            "run_id": run_id,
            "status": "ABORTED_RATE_LIMIT" if "HTTP 429" in str(error) else "ABORTED_ERROR",
            "rows": rows,
            "backbones": backbones,
            "call_count": counts,
            "total_latency_seconds": total_latency,
            "reason": str(error),
            "scope_statement": manifest["scope_statement"],
            "scientific_use_allowed": False,
            "fraction_passing": None,
        }
        digest = store.put_json(report)
        append_event(
            ledger,
            run_id,
            sequence_no,
            "D3_ABORTED",
            {"artifact_digest": digest, "reason": str(error), "call_count": counts},
        )
        report["artifact_digest"] = digest
        report["ledger_chain"] = ledger.verify_chain(run_id).model_dump(mode="json")
        (output_dir / "d3-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report
    passing = [row for row in rows if row.get("passes")]
    report = {
        "manifest": manifest,
        "run_id": run_id,
        "status": "COMPLETED",
        "rows": rows,
        "backbones": backbones,
        "call_count": counts,
        "total_latency_seconds": total_latency,
        "scope_statement": manifest["scope_statement"],
        "scientific_use_allowed": False,
        "fraction_passing": len(passing) / len(rows) if rows else None,
    }
    digest = store.put_json(report)
    append_event(
        ledger,
        run_id,
        sequence_no,
        "D3_COMPLETED",
        {"artifact_digest": digest, "call_count": counts},
    )
    report["artifact_digest"] = digest
    report["ledger_chain"] = ledger.verify_chain(run_id).model_dump(mode="json")
    (output_dir / "d3-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/manifests/design_d3_smallmotif_v1.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/design/d3_smallmotif_v1"))
    args = parser.parse_args()
    result = run(args.manifest, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["status"],
                "artifact_digest": result.get("artifact_digest"),
                "call_count": result["call_count"],
                "fraction_passing": result.get("fraction_passing"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
