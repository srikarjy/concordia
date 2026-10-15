"""Design a binder against a target, then verify it without a reference structure.

    RFdiffusion (backbone) -> ProteinMPNN (sequence) -> Boltz-2 (re-fold) -> verifier

This is the case the structure verifier exists for. A designed binder has no
experimental structure, so DockQ, contact recall and every other reference metric
is undefined. The only admissible evidence is what can be measured from the
predictions themselves: physical plausibility, agreement across diffusion
samples, and a counterfactual in which the predicted paratope is mutated and the
interface is expected to move.

Expect PARTIALLY_SUPPORTED at best from this script alone. Sample agreement comes
from one model, so it cannot supply a second independent evidence family; passing
``--second-model-cif`` with a prediction from a different engine is what makes
SUPPORTED reachable. That ceiling is the verifier working, not failing.

Needs biopython and an NVIDIA API key:

    NVIDIA_API_KEY=... uv run --no-project --with biopython --with httpx --with pydantic \\
        python scripts/design_binder.py TARGET.pdb --contigs 'A20-60/0 50-100' \\
            --hotspots A50 A51 --out-dir WORKDIR

Chain mapping is explicit because RFdiffusion's output chain order is a property
of the contig string, not a guarantee. Check the generated PDB and override
``--target-chain`` / ``--binder-chain`` if they differ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from Bio.PDB import PDBParser  # noqa: E402
from Bio.PDB.Polypeptide import index_to_one, three_to_index  # noqa: E402
from structure_measurements import (  # noqa: E402
    BINDER_ROLES,
    interface_agreement,
    interface_residues,
    physical,
)

from concordia.genomics.boltz_nvidia import (  # noqa: E402
    BoltzComplexRequest,
    NvidiaHostedBoltzRunner,
)
from concordia.genomics.proteinmpnn_nvidia import (  # noqa: E402
    NvidiaHostedProteinMpnnRunner,
    ProteinMpnnRequest,
)
from concordia.genomics.rfdiffusion_nvidia import (  # noqa: E402
    NvidiaHostedRFdiffusionRunner,
    RFdiffusionRequest,
)
from concordia.storage.content import ContentAddressedStore  # noqa: E402
from concordia.verification.cross import (  # noqa: E402
    ClaimRequest,
    ProvenanceArtifact,
    StructureScope,
    verify_claim,
)
from concordia.verification.structure_rules import (  # noqa: E402
    RULE_PACK_VERSION,
    StructureMeasurements,
    evidence_records,
    plausibility,
)

# Boltz relabels output chains A, B, ... in the order polymers are submitted.
BOLTZ_BINDER, BOLTZ_TARGET = "A", "B"


def chain_sequence(pdb_path: Path, chain_id: str) -> str:
    """One-letter sequence of one chain, unknown residues as X."""
    model = PDBParser(QUIET=True).get_structure(pdb_path.stem, str(pdb_path))[0]
    if chain_id not in model:
        raise SystemExit(
            f"chain {chain_id} is not in {pdb_path.name}; chains present: "
            + ", ".join(sorted(c.id for c in model))
        )
    out = []
    for residue in model[chain_id]:
        if residue.id[0] != " ":
            continue
        try:
            out.append(index_to_one(three_to_index(residue.get_resname())))
        except Exception:  # noqa: BLE001 - a non-standard residue becomes X
            out.append("X")
    return "".join(out)


def _predict_complex(
    runner: NvidiaHostedBoltzRunner, binder: str, target: str, out: Path, samples: int
) -> dict:
    """Re-fold the designed pair and write the top structure plus each extra sample."""
    result = runner.predict_complex(
        BoltzComplexRequest(
            polymers=(
                {"id": BOLTZ_BINDER, "molecule_type": "protein", "sequence": binder},
                {"id": BOLTZ_TARGET, "molecule_type": "protein", "sequence": target},
            ),
            diffusion_samples=samples,
        )
    )
    out.write_text(result.structure_text)
    extras = []
    for index, text in enumerate(result.additional_structures, start=1):
        extra = out.with_name(f"{out.stem}.sample{index}.cif")
        extra.write_text(text)
        extras.append(extra)
    return {
        "top": out,
        "samples": extras,
        "confidence": result.confidence_scores[0] if result.confidence_scores else None,
        "score_lists": result.score_lists,
        "response_artifact_digest": result.response_artifact_digest,
    }


def _alanine_scan(sequence: str, positions: set[int]) -> str:
    residues = list(sequence)
    for i in positions:
        if 0 <= i < len(residues):
            residues[i] = "A"
    return "".join(residues)


def _envelope(store: ContentAddressedStore, payload: dict, parents: tuple[str, ...] = ()) -> str:
    digest = store.put_json(payload)
    return store.put_json(
        ProvenanceArtifact(
            kind="evidence" if parents else "sequence",
            payload_digest=digest,
            dependencies=parents,
            execution_mode="recorded_real",
            scientific_use_allowed=True,
            source="de novo binder design run",
            producing_tool=f"design_binder/{RULE_PACK_VERSION}",
        ).model_dump(mode="json")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target_pdb", type=Path)
    parser.add_argument("--contigs", required=True, help="RFdiffusion contig DSL string")
    parser.add_argument("--hotspots", nargs="*", default=[], help="e.g. A50 A51")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--diffusion-steps", type=int, default=50)
    parser.add_argument("--samples", type=int, default=5, help="Boltz diffusion samples")
    parser.add_argument("--target-chain", default="A", help="target chain in RFdiffusion output")
    parser.add_argument("--binder-chain", default="B", help="binder chain in RFdiffusion output")
    parser.add_argument("--second-model-cif", type=Path, help="an independent model's prediction")
    parser.add_argument("--random-seed", type=int)
    args = parser.parse_args()

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    artifacts = ContentAddressedStore(out / "artifacts")
    target_pdb_text = args.target_pdb.read_text()

    print("1/4 RFdiffusion: generating a binder backbone", flush=True)
    backbone = NvidiaHostedRFdiffusionRunner(artifacts).generate(
        RFdiffusionRequest(
            target_pdb=target_pdb_text,
            contigs=args.contigs,
            hotspot_residues=tuple(args.hotspots),
            diffusion_steps=args.diffusion_steps,
            random_seed=args.random_seed,
        )
    )
    backbone_pdb = out / "backbone.pdb"
    backbone_pdb.write_text(backbone.pdb_text)

    print(f"2/4 ProteinMPNN: designing chain {args.binder_chain}", flush=True)
    sequences = NvidiaHostedProteinMpnnRunner(artifacts).design(
        ProteinMpnnRequest(
            input_pdb=backbone.pdb_text,
            design_chains=(args.binder_chain,),
            num_sequences=1,
            random_seed=args.random_seed,
        )
    )
    # The first multi-FASTA record is normally the input sequence, not a design.
    designs = [item for item in sequences.designed_sequences if "input" not in item.header.lower()]
    chosen = (designs or list(sequences.designed_sequences))[-1]
    binder_sequence = chosen.sequence.split("/")[0]
    target_sequence = chain_sequence(backbone_pdb, args.target_chain)
    print(f"    binder {len(binder_sequence)} aa, target {len(target_sequence)} aa", flush=True)

    boltz = NvidiaHostedBoltzRunner(artifacts)
    print(f"3/4 Boltz-2: re-folding the pair with {args.samples} samples", flush=True)
    predicted = _predict_complex(
        boltz, binder_sequence, target_sequence, out / "designed.cif", args.samples
    )

    values: dict = dict(physical(predicted["top"], BINDER_ROLES))
    if predicted["samples"]:
        values["sample_interface_agreement"] = min(
            interface_agreement(predicted["top"], sample, BINDER_ROLES)
            for sample in predicted["samples"]
        )
    if args.second_model_cif:
        values["second_model_interface_agreement"] = interface_agreement(
            predicted["top"], args.second_model_cif, BINDER_ROLES
        )
    if predicted["confidence"] is not None:
        values["self_reported_confidence"] = predicted["confidence"]

    print("4/4 counterfactual: mutating the predicted paratope and re-folding", flush=True)
    paratope = {index for _, index in interface_residues(predicted["top"], BINDER_ROLES)}
    perturbed_sequence = _alanine_scan(binder_sequence, paratope)
    if perturbed_sequence == binder_sequence:
        print("    no paratope found; skipping the counterfactual", flush=True)
    else:
        perturbed = _predict_complex(
            boltz, perturbed_sequence, target_sequence, out / "perturbed.cif", 1
        )
        values["perturbed_paratope_interface_agreement"] = interface_agreement(
            predicted["top"], perturbed["top"], BINDER_ROLES
        )

    measured = StructureMeasurements(**values)
    settings = {
        "contigs": args.contigs,
        "hotspots": args.hotspots,
        "diffusion_steps": args.diffusion_steps,
        "boltz_samples": args.samples,
    }
    scope = StructureScope(
        complex_id=f"design-{backbone.input_payload_hash[:12]}",
        receptor_chains=(BOLTZ_BINDER,),
        ligand_chains=(BOLTZ_TARGET,),
        model_checkpoint="ipd/rfdiffusion+ipd/proteinmpnn+mit/boltz2",
        settings_digest=hashlib.sha256(
            json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        assay="designed_binder_interface",
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = ContentAddressedStore(Path(tmp))
        source = _envelope(store, {"binder_length": len(binder_sequence)})
        measured_json = measured.model_dump(mode="json", exclude_none=True)
        evidence_artifacts = {
            name: _envelope(store, {"signal": name, **measured_json}, (source,))
            for name in ("physical", "samples", "second_model", "counterfactual")
        }
        claim = ClaimRequest(
            claim_id=scope.complex_id,
            text="The designed binder's predicted interface with the target is real.",
            scope=scope,
            source_sequence=source,
            evidence=evidence_records(measured, scope, evidence_artifacts),
        )
        verdict = verify_claim(claim, store)

    report = {
        "rule_pack": RULE_PACK_VERSION,
        "settings": settings,
        "binder_sequence": binder_sequence,
        "inverse_folding_score": chosen.score,
        "measurements": measured_json,
        "physical_findings": list(plausibility(measured)[1]),
        "status": verdict.status.value,
        "reasons": list(verdict.reasons),
        "artifacts": {
            "rfdiffusion_response": backbone.response_artifact_digest,
            "proteinmpnn_response": sequences.response_artifact_digest,
            "boltz_response": predicted["response_artifact_digest"],
        },
        "no_reference_structure": (
            "A designed binder has no experimental structure, so DockQ and every other "
            "reference metric is undefined. Nothing here shows the binder works."
        ),
    }
    (out / "design-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "reasons", "physical_findings")}, indent=2))


if __name__ == "__main__":
    main()
