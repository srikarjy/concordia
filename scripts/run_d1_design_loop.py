"""Run the pre-registered RFdiffusion -> ProteinMPNN -> Boltz-2 D1 loop.

This is a bounded hosted experiment.  It writes only redacted request metadata,
content-addressed response artifacts, and computational scope-limited results.
It never turns pLDDT, pTM, or RMSD into a biological claim.
"""

from __future__ import annotations

import argparse
import json
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
    motif_refusal,
    render_scope_statement,
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


def _call_with_429_retry(call: Callable[[], T], retry_delay_seconds: float) -> T:
    try:
        return call()
    except RuntimeError as error:
        if "HTTP 429" not in str(error):
            raise
        time.sleep(retry_delay_seconds)
        try:
            return call()
        except RuntimeError as retry_error:
            raise RuntimeError(
                "hosted route remained rate-limited after one retry"
            ) from retry_error


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") not in {
        "pre_registered_before_campaign_generation",
        "pre_registered_before_pilot",
    }:
        raise ValueError("D1 manifest is not marked pre-registered before generation")
    return manifest


def _append(
    ledger: SQLiteEventLedger,
    run_id: str,
    sequence: int,
    kind: str,
    payload: dict[str, Any],
) -> int:
    ledger.append(run_id, kind, payload, expected_sequence=sequence)
    return sequence + 1


def _response_metrics(store: ContentAddressedStore, response_digest: str) -> dict[str, Any]:
    payload = json.loads(store.get_bytes(response_digest))
    confidence = payload.get("confidence_scores")
    plddt_mean = None
    if isinstance(confidence, list) and confidence:
        numeric = [float(value) for value in confidence if isinstance(value, int | float)]
        if numeric:
            plddt_mean = sum(numeric) / len(numeric)
    ptm = payload.get("ptm")
    if ptm is None:
        ptm = payload.get("pTM")
    return {"plddt_mean_reported": plddt_mean, "ptm_reported": ptm}


def run(manifest_path: Path, output_dir: Path, pilot: bool = False) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    target = manifest["target"]
    pdb_path = Path(target["pdb_path"])
    target_pdb = pdb_path.read_text(encoding="utf-8")
    expected_retained = "QLSKEELKLLLQTEFPSLLKGPSTLDELFEELDKNGDGEVSFEE"
    motif_positions = tuple(int(value) - 21 for value in target["motif_local_positions"])
    motif_letters = target["motif_letters"]
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = ContentAddressedStore(output_dir / "artifacts")
    ledger = SQLiteEventLedger(output_dir / "events.sqlite3")
    run_id = str(uuid.uuid4())
    request_payload = {"manifest": str(manifest_path), "campaign": manifest["campaign"]}
    command_digest = request_digest(request_payload)
    ledger.create_run(
        run_id=run_id,
        idempotency_key=f"d1:{command_digest}",
        command_digest=command_digest,
        payload=request_payload,
        event_id=str(uuid.uuid4()),
    )
    sequence_number = 1
    sequence_number = _append(ledger, run_id, sequence_number, "D1_PREREGISTERED", {
        "manifest_path": str(manifest_path),
        "success_criterion": manifest["success_criterion"],
        "protected_residues": target["motif_local_positions"],
    })
    key = nvidia_api_key(Path("."))
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is required for D1")
    rf = NvidiaHostedRFdiffusionRunner(artifacts, api_key=key, timeout_seconds=300)
    mpnn = NvidiaHostedProteinMpnnRunner(artifacts, api_key=key, timeout_seconds=300)
    boltz = NvidiaHostedBoltzRunner(artifacts, api_key=key, timeout_seconds=320)
    hotspot_residues = tuple(f"A{position}" for position in target["motif_local_positions"])
    rows: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    call_count = {"rfdiffusion": 0, "proteinmpnn": 0, "boltz2": 0}
    total_latency = 0.0
    phase = manifest["pilot"] if pilot else manifest["generation"]
    sequence_count = int(phase["sequences_per_backbone"])
    delay_seconds = float(
        phase.get("inter_call_delay_seconds", manifest["generation"]["inter_call_delay_seconds"])
    )
    retry_delay_seconds = float(manifest["generation"]["rate_limit_retry_delay_seconds"])
    seeds = tuple(int(seed) for seed in phase["rfdiffusion_seeds"])
    last_boltz_call_at: float | None = None

    def write_abort(reason: str) -> dict[str, Any]:
        artifact_payload = {
            "manifest": manifest,
            "run_id": run_id,
            "phase": "pilot" if pilot else "campaign",
            "status": "ABORTED_RATE_LIMIT" if "rate-limited" in reason else "ABORTED_ERROR",
            "rows": rows,
            "refusals": refusals,
            "call_count": call_count,
            "total_latency_seconds": total_latency,
            "reason": reason,
            "scope_statement": render_scope_statement(),
            "scientific_use_allowed": False,
            "fraction_passing": None,
        }
        report_digest = artifacts.put_json(artifact_payload)
        _append(ledger, run_id, sequence_number, "D1_ABORTED", {
            "artifact_digest": report_digest,
            "reason": reason,
            "call_count": call_count,
        })
        artifact_payload["ledger_chain"] = ledger.verify_chain(run_id).model_dump(mode="json")
        artifact_payload["artifact_digest"] = report_digest
        (output_dir / "d1-report.json").write_text(
            json.dumps(artifact_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return artifact_payload

    for backbone_index, seed in enumerate(seeds, start=1):
        rf_result = _call_with_429_retry(
            lambda seed=seed: rf.generate(
                RFdiffusionRequest(
                    target_pdb=target_pdb,
                    contigs=target["contig"],
                    hotspot_residues=hotspot_residues,
                    diffusion_steps=50,
                    random_seed=seed,
                )
            ),
            retry_delay_seconds,
        )
        call_count["rfdiffusion"] += 1
        total_latency += rf_result.elapsed_seconds
        backbone_path = output_dir / f"backbone_{backbone_index:02d}.pdb"
        backbone_path.write_text(rf_result.pdb_text, encoding="utf-8")
        backbone_structure = load_structure(rf_result.pdb_text, "pdb", f"backbone-{backbone_index}")
        target_chain, _ = find_retained_target(backbone_structure, expected_retained)
        target_chain_id = target_chain.id
        chain_sequences = {chain.id: chain_sequence(chain) for chain in backbone_structure[0]}
        binder_candidates = [
            (chain_id, sequence)
            for chain_id, sequence in chain_sequences.items()
            if chain_id != target_chain_id
        ]
        if len(binder_candidates) != 1:
            raise RuntimeError(
                f"backbone {backbone_index} did not have exactly one generated chain"
            )
        binder_chain_id, binder_backbone_sequence = binder_candidates[0]
        def design_sequences(
            rf_result=rf_result,
            binder_chain_id=binder_chain_id,
        ):
            return mpnn.design(
                ProteinMpnnRequest(
                    input_pdb=rf_result.pdb_text,
                    design_chains=(binder_chain_id,),
                    num_sequences=sequence_count,
                    sampling_temperature=float(manifest["generation"]["proteinmpnn_sampling_temperature"]),
                    random_seed=int(manifest["generation"]["proteinmpnn_seed"]),
                )
            )

        mpnn_result = _call_with_429_retry(design_sequences, retry_delay_seconds)
        call_count["proteinmpnn"] += 1
        total_latency += mpnn_result.elapsed_seconds
        records = parse_mfasta("\n".join(
            f">{item.header}\n{item.sequence}" for item in mpnn_result.designed_sequences
        ))
        designs = [record for record in records if "input" not in record[0].lower()]
        if len(designs) < sequence_count:
            raise RuntimeError(
                f"ProteinMPNN returned fewer than {sequence_count} designed sequences for "
                f"backbone {backbone_index}"
            )
        for sequence_index, (_, raw_sequence) in enumerate(designs[:sequence_count], start=1):
            parts = raw_sequence.split("/")
            binder_sequence = next(
                (
                    part
                    for part in parts
                    if len(part) == len(binder_backbone_sequence)
                ),
                raw_sequence,
            )
            if len(binder_sequence) != len(binder_backbone_sequence):
                raise RuntimeError(
                    "ProteinMPNN designed sequence length does not match RFdiffusion "
                    f"chain: {len(binder_sequence)} != {len(binder_backbone_sequence)}"
                )
            target_sequence = expected_retained
            violation = motif_refusal(
                sequence=target_sequence,
                motif_positions=tuple(position + 1 for position in motif_positions),
                motif_letters=motif_letters,
                accession=target["uniprot_accession"],
                feature_type=target["protected_feature"],
            )
            if violation is not None:
                refusal = {
                    "backbone_id": backbone_index,
                    "sequence_id": sequence_index,
                    **violation.as_dict(),
                }
                refusals.append(refusal)
                rows.append(
                    {
                        "backbone_id": backbone_index,
                        "sequence_id": sequence_index,
                        "refusal": refusal,
                    }
                )
                continue
            def refold(
                binder_sequence=binder_sequence,
                target_sequence=target_sequence,
            ):
                return boltz.predict_complex(
                    BoltzComplexRequest(
                        polymers=(
                            BoltzPolymer(id="A", molecule_type="protein", sequence=binder_sequence),
                            BoltzPolymer(id="B", molecule_type="protein", sequence=target_sequence),
                        ),
                        diffusion_samples=1,
                    )
                )

            if last_boltz_call_at is not None:
                elapsed_since_last = time.monotonic() - last_boltz_call_at
                if elapsed_since_last < delay_seconds:
                    time.sleep(delay_seconds - elapsed_since_last)
            last_boltz_call_at = time.monotonic()
            try:
                boltz_result = _call_with_429_retry(refold, retry_delay_seconds)
            except RuntimeError as error:
                if "rate-limited" in str(error):
                    return write_abort(str(error))
                raise
            call_count["boltz2"] += 1
            total_latency += boltz_result.elapsed_seconds
            metrics = _response_metrics(artifacts, boltz_result.response_artifact_digest)
            comparison = compare_structures(
                rf_result.pdb_text,
                "pdb",
                boltz_result.structure_text,
                boltz_result.structure_format,
                expected_retained,
                motif_positions,
            )
            recovery = sequence_recovery(binder_sequence, expected_retained)
            row = {
                "backbone_id": backbone_index,
                "sequence_id": sequence_index,
                "sc_rmsd_angstrom": comparison.global_rmsd_angstrom,
                "motif_rmsd_angstrom": comparison.motif_rmsd_angstrom,
                "global_ca_atoms_aligned": comparison.global_ca_atoms,
                "motif_ca_atoms_aligned": comparison.motif_ca_atoms,
                "global_superposition": comparison.global_superposition,
                "sequence_recovery_vs_1igv_retained_wildtype": recovery,
                **metrics,
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
    passing = [row for row in rows if row.get("passes") is True]
    artifact_payload = {
        "manifest": manifest,
        "run_id": run_id,
        "phase": "pilot" if pilot else "campaign",
        "rows": rows,
        "refusals": refusals,
        "call_count": call_count,
        "total_latency_seconds": total_latency,
        "scope_statement": render_scope_statement(),
        "scientific_use_allowed": False,
        "fraction_passing": len(passing) / max(len(rows), 1),
    }
    report_digest = artifacts.put_json(artifact_payload)
    sequence_number = _append(ledger, run_id, sequence_number, "D1_COMPLETED", {
        "artifact_digest": report_digest,
        "call_count": call_count,
        "refusal_count": len(refusals),
    })
    artifact_payload["ledger_chain"] = ledger.verify_chain(run_id).model_dump(mode="json")
    artifact_payload["ledger_last_sequence"] = sequence_number - 1
    artifact_payload["artifact_digest"] = report_digest
    (output_dir / "d1-report.json").write_text(
        json.dumps(artifact_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/design_d1_1igv_preregistration_v5.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/design/d1_1igv"))
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    result = run(args.manifest, args.output_dir, pilot=args.pilot)
    print(json.dumps({
        "artifact_digest": result["artifact_digest"],
        "call_count": result["call_count"],
        "refusal_count": len(result["refusals"]),
        "fraction_passing": result["fraction_passing"],
        "scope_statement": result["scope_statement"],
    }, indent=2))


if __name__ == "__main__":
    main()
