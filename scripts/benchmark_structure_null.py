"""Run the independent geometry-only control on a frozen antibody benchmark.

The input is the existing verifier report produced without exposing the crystal
structure to the verifier.  Its ``label_correct`` field is used only as a
retrospective benchmark label.  The baseline consumes physical measurements and
deliberately ignores DockQ, confidence, sample agreement, and counterfactual
fields.

    PYTHONPATH=src python scripts/benchmark_structure_null.py \
        reports/verifier-on-boltz-benchmark.json \
        --output reports/structure-null-baseline-benchmark.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from concordia.verification.structure_baseline import (  # noqa: E402
    StructureBaselineCase,
    run_structure_baseline,
)


def build_report(source: dict, *, source_digest: str, source_path: str) -> dict[str, object]:
    cases = tuple(
        StructureBaselineCase(
            case_id=row["pdb_id"],
            measurements=row["measurements"],
            reference_supported=row["label_correct"],
        )
        for row in source["results"]
        if "measurements" in row and "label_correct" in row
    )
    result = run_structure_baseline(cases).model_dump(mode="json")
    return {
        "schema_version": 1,
        "source_report": source_path,
        "source_report_sha256": source_digest,
        "held_out_label": source.get("label"),
        "measurement_fields_used": (
            "clash_count",
            "variable_domain_fraction",
            "buried_surface_area",
        ),
        "measurement_fields_ignored": (
            "reference_dockq",
            "self_reported_confidence",
            "sample_interface_agreement",
            "second_model_interface_agreement",
            "perturbed_paratope_interface_agreement",
        ),
        "baseline": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    source = json.loads(raw)
    result = build_report(
        source,
        source_digest=hashlib.sha256(raw).hexdigest(),
        source_path=str(args.report),
    )
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(json.dumps(result["baseline"]["metrics"], indent=2))


if __name__ == "__main__":
    main()
