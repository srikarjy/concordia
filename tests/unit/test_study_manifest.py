from pathlib import Path

import pytest
import yaml

from concordia.scientific import StudyInputManifest, StudyProtocol, StudyStatus

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_hbb_pilot_inputs_and_protocol_are_valid() -> None:
    inputs = StudyInputManifest.model_validate(
        yaml.safe_load((ROOT / "configs/studies/hbb_promoter_inputs.yaml").read_text())
    )
    protocol = StudyProtocol.model_validate(
        yaml.safe_load((ROOT / "configs/studies/hbb_promoter_protocol.yaml").read_text())
    )

    assert inputs.status == "FROZEN"
    assert len(inputs.variants) == 2
    assert all(variant.variant_offset == 4096 for variant in inputs.variants)
    assert protocol.status is StudyStatus.FROZEN
    assert protocol.dataset_id == inputs.cohort_id
    assert protocol.window_size == inputs.window_size


def test_study_manifest_rejects_coordinate_drift() -> None:
    raw = yaml.safe_load((ROOT / "configs/studies/hbb_promoter_inputs.yaml").read_text())
    raw["variants"][0]["zero_based_position"] += 1

    with pytest.raises(ValueError, match="positions disagree"):
        StudyInputManifest.model_validate(raw)


def test_encode_annotation_manifest_preserves_negative_variant_overlap() -> None:
    annotation = yaml.safe_load(
        (ROOT / "configs/studies/hbb_promoter_annotations.yaml").read_text()
    )

    assert annotation["source"]["assembly"] == "GRCh38"
    assert annotation["source"]["source_md5"] == "04653af177917b3dda96b9454fd8f90e"
    assert len(annotation["intervals"]) == 2
    assert not any(annotation["variant_overlap"].values())
    assert annotation["status"] == "SOURCE_VALIDATED_AWAITING_MODEL_COMPARISON"
