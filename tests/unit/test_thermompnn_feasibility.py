from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from concordia.protein_xai.thermompnn import (
    FeasibilityPilot,
    PilotRefusal,
    PilotRequest,
    build_feasibility_record,
    replay_record,
)

ROOT = Path(__file__).resolve().parents[2]
PDB = ROOT / "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb"
MANIFEST = ROOT / "data/manifests/tsuboyama_rule2_manifest_v3.json"


def request(**changes: object) -> PilotRequest:
    values: dict[str, object] = {
        "structure_path": PDB,
        "manifest_path": MANIFEST,
        "chain_id": "A",
        "position": 1,
        "wildtype": "S",
        "mutant": "A",
        "variant_id": "1IGV.pdb_S1A",
    }
    values.update(changes)
    return PilotRequest(**values)  # type: ignore[arg-type]


def test_unavailable_record_keeps_exact_input_and_model_blocker() -> None:
    record = build_feasibility_record(FeasibilityPilot(request()))
    assert record["status"] == "unavailable"
    assert record["preflight"]["structure"]["sequence"].startswith("S")
    assert record["preflight"]["structure"]["mapping"][0]["residue_number"] == 1
    assert "source root was not provided" in record["terminal_reason"]
    assert record["target"]["formula"] == "f = -raw ThermoMPNN ddG"
    assert record["scientific_use_allowed"] is False


def test_refuses_wildtype_mismatch_before_any_model_access() -> None:
    with pytest.raises(PilotRefusal, match="wildtype mismatch"):
        FeasibilityPilot(request(wildtype="A", mutant="C")).preflight()


def test_replay_requires_exact_record_bytes(tmp_path: Path) -> None:
    record = build_feasibility_record(FeasibilityPilot(request()))
    path = tmp_path / "record.json"
    content = json.dumps(record, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8")
    path.with_suffix(".json.sha256").write_text(
        hashlib.sha256(content.encode()).hexdigest() + "\n", encoding="utf-8"
    )
    assert replay_record(path)["status"] == "unavailable"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        replay_record(path)
