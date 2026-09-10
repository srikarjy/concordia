from pathlib import Path

import yaml

from concordia.virtual_cell import CellxgeneDatasetSource, StateSourcePin

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_cellxgene_and_state_source_pins_are_valid() -> None:
    cellxgene = CellxgeneDatasetSource.model_validate(
        yaml.safe_load(
            (ROOT / "configs/virtual_cell/cellxgene_shh_e12_5.yaml").read_text()
        )
    )
    state = StateSourcePin.model_validate(
        yaml.safe_load((ROOT / "configs/virtual_cell/state_source.yaml").read_text())
    )

    assert cellxgene.asset_byte_size == 29_755_471
    assert cellxgene.required_perturbations == ("Control", "SBE1/5")
    assert state.package_version == "0.11.3"
    assert state.model_terms_status == "NOT_ACCEPTED"
