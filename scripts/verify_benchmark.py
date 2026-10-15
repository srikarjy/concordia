"""Run the structure-claim verifier on benchmark predictions, with the crystal held out.

For each complex the claim is "the predicted antibody-antigen interface is
correct". The verifier sees only evidence measurable without the experimental
structure. DockQ against the crystal is used afterwards as the label, so the
report measures how often the verifier supports a wrong pose (false pass) and
how often it withholds support from a correct one (false fail).

Optional extra predictions in WORKDIR, by file name, add evidence families:
    {PDB}.sample1.cif ...   further diffusion samples of the same model
    {PDB}.second.cif        an independent model, e.g. AlphaFold 3
    {PDB}.perturbed.cif     the same model with the predicted paratope mutated

    uv run --no-project --with biopython --with pydantic \\
        python scripts/verify_benchmark.py reports/boltz2-post-cutoff-antibody-benchmark.json \\
        WORKDIR --output reports/verifier-on-boltz-benchmark.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from structure_measurements import interface_agreement, physical  # noqa: E402

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

PASSING = {"SUPPORTED"}


def _envelope(store: ContentAddressedStore, kind: str, payload: dict, parents=()) -> str:
    digest = store.put_json(payload)
    return store.put_json(
        ProvenanceArtifact(
            kind=kind,
            payload_digest=digest,
            dependencies=parents,
            execution_mode="recorded_real",
            # Granted for this offline evaluation only: the predictions are real recorded
            # model outputs, and the verifier is what decides what they support.
            scientific_use_allowed=True,
            source="post-cutoff antibody benchmark",
            producing_tool=f"verify_benchmark/{RULE_PACK_VERSION}",
        ).model_dump(mode="json")
    )


def _measure(row: dict, workdir: Path) -> StructureMeasurements:
    pdb = row["pdb_id"]
    pred = workdir / f"{pdb}.pred.cif"
    values: dict = {**physical(pred), "reference_dockq": row["scores"]["dockq"]}
    samples = sorted(workdir.glob(f"{pdb}.sample*.cif"))
    if samples:
        values["sample_interface_agreement"] = min(interface_agreement(pred, s) for s in samples)
    for name, field in (
        ("second", "second_model_interface_agreement"),
        ("perturbed", "perturbed_paratope_interface_agreement"),
    ):
        extra = workdir / f"{pdb}.{name}.cif"
        if extra.exists():
            values[field] = interface_agreement(pred, extra)
    if row.get("model_confidence") is not None:
        values["self_reported_confidence"] = row["model_confidence"]
    return StructureMeasurements(**values)


def evaluate(report: dict, workdir: Path) -> dict:
    settings = report.get("prediction_settings", {})
    settings_digest = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        store = ContentAddressedStore(Path(tmp))
        for row in report["results"]:
            if "scores" not in row or "dockq" not in row["scores"]:
                continue
            measured = _measure(row, workdir)
            scope = StructureScope(
                complex_id=row["pdb_id"],
                receptor_chains=("H", "L"),
                ligand_chains=("A",),
                model_checkpoint="mit/boltz2",
                settings_digest=settings_digest,
                assay="antibody_antigen_interface",
            )
            source = _envelope(store, "sequence", {"input_payload_hash": row["input_payload_hash"]})
            measured_json = measured.model_dump(mode="json", exclude_none=True)
            artifacts = {
                name: _envelope(store, "evidence", {"signal": name, **measured_json}, (source,))
                for name in ("physical", "samples", "second_model", "counterfactual")
            }
            claim = ClaimRequest(
                claim_id=row["pdb_id"],
                text="The predicted antibody-antigen interface is correct.",
                scope=scope,
                source_sequence=source,
                evidence=evidence_records(measured, scope, artifacts),
            )
            result = verify_claim(claim, store)
            correct = row["scores"]["capri_class"] != "incorrect"
            rows.append(
                {
                    "pdb_id": row["pdb_id"],
                    "label_correct": correct,
                    "dockq": row["scores"]["dockq"],
                    "self_reported_confidence": measured.self_reported_confidence,
                    "measurements": measured_json,
                    "physical_findings": list(plausibility(measured)[1]),
                    "status": result.status.value,
                    "reasons": list(result.reasons),
                }
            )
    passed = [r for r in rows if r["status"] in PASSING]
    wrong = [r for r in rows if not r["label_correct"]]
    right = [r for r in rows if r["label_correct"]]
    return {
        "rule_pack": RULE_PACK_VERSION,
        "label": "DockQ >= 0.23 against the experimental structure (CAPRI acceptable)",
        "held_out": "The experimental structure is never given to the verifier.",
        "passing_statuses": sorted(PASSING),
        "results": rows,
        "summary": {
            "n": len(rows),
            "correct_poses": len(right),
            "incorrect_poses": len(wrong),
            "false_pass": sum(r in passed for r in wrong),
            "false_fail": sum(r not in passed for r in right),
            "contradicted": sum(r["status"] == "CONTRADICTED" for r in rows),
            "statuses": {
                s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.report.read_text()), args.workdir)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(json.dumps(result["summary"], indent=2))
    for row in result["results"]:
        print(
            row["pdb_id"],
            "correct" if row["label_correct"] else "wrong",
            row["status"],
            row["physical_findings"],
        )


if __name__ == "__main__":
    main()
