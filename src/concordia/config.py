"""Configuration loading and validation for reproducible runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    assay: str
    url: str
    raw_path: Path
    checksum_sha256: str | None


@dataclass(frozen=True)
class FingerprintConfig:
    radius: int
    n_bits: int
    include_chirality: bool


@dataclass(frozen=True)
class SplitConfig:
    seed: int
    train_fraction: float
    validation_fraction: float
    test_fraction: float


@dataclass(frozen=True)
class ModelConfig:
    seed: int
    n_estimators: int
    class_weight: str | None
    n_jobs: int


@dataclass(frozen=True)
class BaselineConfig:
    schema_version: int
    dataset: DatasetConfig
    fingerprint: FingerprintConfig
    split: SplitConfig
    model: ModelConfig
    artifact_directory: Path
    source_path: Path
    raw: dict[str, Any]


def load_baseline_config(path: str | Path) -> BaselineConfig:
    """Load a baseline YAML configuration and enforce key invariants."""
    source_path = Path(path)
    with source_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping")
    if raw.get("schema_version") != 1:
        raise ValueError("Only configuration schema_version 1 is supported")

    dataset = raw["dataset"]
    fingerprint = raw["fingerprint"]
    split = raw["split"]
    model = raw["model"]

    fractions = (
        float(split["train_fraction"]),
        float(split["validation_fraction"]),
        float(split["test_fraction"]),
    )
    if any(value <= 0 for value in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("Split fractions must be positive and sum to 1")
    if fingerprint.get("kind") != "morgan":
        raise ValueError("The baseline supports only Morgan fingerprints")
    if split.get("strategy") != "scaffold":
        raise ValueError("The baseline supports only scaffold splitting")
    if model.get("kind") != "random_forest":
        raise ValueError("The baseline supports only Random Forest")

    return BaselineConfig(
        schema_version=1,
        dataset=DatasetConfig(
            name=str(dataset["name"]),
            assay=str(dataset["assay"]),
            url=str(dataset["url"]),
            raw_path=Path(dataset["raw_path"]),
            checksum_sha256=dataset.get("checksum_sha256"),
        ),
        fingerprint=FingerprintConfig(
            radius=int(fingerprint["radius"]),
            n_bits=int(fingerprint["n_bits"]),
            include_chirality=bool(fingerprint["include_chirality"]),
        ),
        split=SplitConfig(
            seed=int(split["seed"]),
            train_fraction=fractions[0],
            validation_fraction=fractions[1],
            test_fraction=fractions[2],
        ),
        model=ModelConfig(
            seed=int(model["seed"]),
            n_estimators=int(model["n_estimators"]),
            class_weight=model.get("class_weight"),
            n_jobs=int(model["n_jobs"]),
        ),
        artifact_directory=Path(raw["artifacts"]["directory"]),
        source_path=source_path,
        raw=raw,
    )
