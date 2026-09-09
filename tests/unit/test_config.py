from pathlib import Path

import pytest

from concordia.config import load_baseline_config


def test_repository_baseline_configuration_is_valid() -> None:
    config = load_baseline_config(Path("configs/baseline_nr_ahr.yaml"))
    assert config.dataset.assay == "NR-AhR"
    assert config.fingerprint.n_bits == 2048


def test_split_fractions_must_sum_to_one(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """schema_version: 1
dataset: {name: tox21, assay: NR-AhR, url: x, raw_path: x, checksum_sha256: null}
fingerprint: {kind: morgan, radius: 2, n_bits: 32, include_chirality: true}
split:
  {strategy: scaffold, seed: 1, train_fraction: 0.8,
   validation_fraction: 0.2, test_fraction: 0.2}
model: {kind: random_forest, seed: 1, n_estimators: 10, class_weight: null, n_jobs: 1}
artifacts: {directory: artifacts/test}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sum to 1"):
        load_baseline_config(path)
