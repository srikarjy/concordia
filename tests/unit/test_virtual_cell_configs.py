from pathlib import Path

import yaml

from concordia.virtual_cell import (
    CellxgeneDatasetSource,
    StateReleaseFileRole,
    StateReleaseSelection,
    StateSourcePin,
)

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


def test_state_release_selection_is_separate_from_source_terms_status() -> None:
    source = StateSourcePin.model_validate(
        yaml.safe_load((ROOT / "configs/virtual_cell/state_source.yaml").read_text())
    )
    release = StateReleaseSelection.model_validate(
        yaml.safe_load((ROOT / "configs/virtual_cell/state_k562_release.yaml").read_text())
    )

    assert source.model_terms_status == "NOT_ACCEPTED"
    assert release.terms.status == "ACCEPTED_BY_USER"
    assert release.terms.use_scope == "NON_COMMERCIAL"
    assert not release.terms.commercial_use_allowed
    assert release.file_for(StateReleaseFileRole.CHECKPOINT).sha256 == (
        "ca790099b46a87999bd030af24805cd48f8601b3d5eb17724ea4335dad3d7d60"
    )
    assert release.file_for(StateReleaseFileRole.DATASET).sha256 == (
        "d150cdd890c8c9434bed169697fd6a31059bedfc4bdd714b11f1c6a4ab3a7adf"
    )
    assert release.dataset.cell_count == 188_590
    assert release.dataset.gene_count == 2_000
