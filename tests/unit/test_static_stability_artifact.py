from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_static_stability_artifact import verify_artifact


def test_static_stability_artifact_has_the_preregistered_digest() -> None:
    report = verify_artifact()
    assert report["structure"]["source"].startswith("Tsuboyama bundled AlphaFold")


def test_static_stability_artifact_rejects_a_modified_payload(tmp_path: Path) -> None:
    source = Path("frontend/public/data/stability.json")
    value = json.loads(source.read_text(encoding="utf-8"))
    value["domain_id"] = "tampered"
    mutated = tmp_path / "stability.json"
    mutated.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        verify_artifact(mutated)
