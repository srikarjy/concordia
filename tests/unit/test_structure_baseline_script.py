"""The frozen antibody baseline script preserves source and label boundaries."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "benchmark_structure_null.py"
_SPEC = importlib.util.spec_from_file_location("benchmark_structure_null", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_report = _MODULE.build_report


def test_structure_null_script_uses_external_labels_and_ignores_reference_fields():
    report = build_report(
        {
            "label": "DockQ against held-out crystal",
            "results": [
                {
                    "pdb_id": "positive",
                    "label_correct": True,
                    "measurements": {
                        "clash_count": 0,
                        "variable_domain_fraction": 1.0,
                        "buried_surface_area": 1700,
                        "reference_dockq": 0.01,
                    },
                },
                {
                    "pdb_id": "negative",
                    "label_correct": False,
                    "measurements": {
                        "clash_count": 16,
                        "variable_domain_fraction": 1.0,
                        "buried_surface_area": 1700,
                        "reference_dockq": 0.99,
                    },
                },
            ],
        },
        source_digest="a" * 64,
        source_path="fixture.json",
    )
    assert report["source_report_sha256"] == "a" * 64
    assert report["baseline"]["metrics"]["balanced_accuracy"] == 1.0
    assert "reference_dockq" in report["measurement_fields_ignored"]
    assert report["baseline"]["scientific_use_allowed"] is False
