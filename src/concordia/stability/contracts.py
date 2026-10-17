"""Sign-safe, content-addressed contracts for measured stability data."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

INTERNAL_STABILITY_DDG_CONVENTION = "ddg_kcal_higher_is_more_stable"


@dataclass(frozen=True)
class DestabilizingDDG:
    """Foreign FoldX/Rosetta-style value; it cannot be mistaken for a model label."""

    kcal_per_mol: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.kcal_per_mol):
            raise ValueError("stability score must be finite")


@dataclass(frozen=True)
class StabilityDDG:
    """Internal convention: larger values mean more stable."""

    kcal_per_mol: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.kcal_per_mol):
            raise ValueError("stability score must be finite")


@dataclass(frozen=True)
class StabilityObservation:
    """Typed internal observation; callers cannot supply a raw external float."""

    variant_id: str
    sequence: str
    ddg_kcal_higher_is_more_stable: StabilityDDG


def from_destabilizing(value: DestabilizingDDG) -> StabilityDDG:
    """Convert FoldX/Rosetta's positive-is-destabilizing value."""
    return StabilityDDG(-value.kcal_per_mol)


def from_stability(value: float) -> StabilityDDG:
    """Wrap a source value that already uses the internal stability convention."""
    return StabilityDDG(value)


def anchor_wild_type(
    rows: list[dict[str, Any]], *, wild_type_sequence: str, tolerance: float = 1e-8
) -> list[dict[str, Any]]:
    """Insert or validate the explicit wild-type row at exactly zero."""
    normalized = "".join(wild_type_sequence.upper().split())
    if not normalized:
        raise ValueError("wild-type sequence is required")
    matches = [row for row in rows if _normalized_sequence(row) == normalized]
    if len(matches) > 1:
        raise ValueError("stability table contains duplicate wild-type rows")
    if matches:
        value = _required_value(matches[0], "ddg_kcal_higher_is_more_stable")
        if abs(float(value)) > tolerance:
            raise ValueError("wild-type stability label must be anchored at zero")
        matches[0]["is_wild_type"] = True
        return rows
    return [
        {
            "variant_id": "wild_type",
            "sequence": normalized,
            "ddg_kcal_higher_is_more_stable": 0.0,
            "is_wild_type": True,
        },
        *rows,
    ]


def validate_wild_type_anchor(
    rows: list[dict[str, Any]], *, wild_type_sequence: str, tolerance: float = 1e-9
) -> None:
    """Fail closed if the explicit wild-type invariant is absent or wrong."""
    normalized = "".join(wild_type_sequence.upper().split())
    matches = [row for row in rows if _normalized_sequence(row) == normalized]
    if len(matches) != 1:
        raise ValueError("stability table must contain exactly one wild-type row")
    value = _required_value(matches[0], "ddg_kcal_higher_is_more_stable")
    if abs(float(value)) > tolerance:
        raise ValueError("wild-type stability label must be anchored at zero")


def freeze_manifest(payload: Mapping[str, Any], path: str | Path) -> StabilityDatasetManifest:
    """Write a manifest once; changing it requires a new path and new holdout."""
    destination = Path(path)
    canonical = canonical_json(dict(payload))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    manifest = StabilityDatasetManifest(
        schema_version=1,
        manifest_digest=digest,
        payload=dict(payload),
    )
    if destination.exists():
        existing = destination.read_text(encoding="utf-8")
        if existing != manifest.model_dump_json(indent=2) + "\n":
            raise FileExistsError("stability manifest already exists with different content")
        return manifest
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


class StabilityDatasetManifest:
    """Small dependency-free manifest model with a stable wire representation."""

    def __init__(self, *, schema_version: int, manifest_digest: str, payload: dict[str, Any]):
        self.schema_version = schema_version
        self.manifest_digest = manifest_digest
        self.payload = payload

    def model_dump_json(self, *, indent: int = 2) -> str:
        return json.dumps(
            _canonicalize(
                {
                    "schema_version": self.schema_version,
                    "manifest_digest": self.manifest_digest,
                    **self.payload,
                }
            ),
            sort_keys=True,
            indent=indent,
            allow_nan=False,
        )


def _canonicalize(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _canonicalize(value.item())
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite values cannot be included in a stability digest")
    return value


def _normalized_sequence(row: Mapping[str, Any]) -> str:
    value = _required_value(row, "sequence")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("required field 'sequence' is missing")
    return "".join(value.upper().split())


def _required_value(row: Mapping[str, Any], field: str) -> Any:
    try:
        return row[field]
    except KeyError as error:
        raise ValueError(f"required field {field!r} is missing") from error


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


__all__ = [
    "INTERNAL_STABILITY_DDG_CONVENTION",
    "DestabilizingDDG",
    "StabilityDDG",
    "StabilityObservation",
    "StabilityDatasetManifest",
    "anchor_wild_type",
    "canonical_json",
    "from_destabilizing",
    "from_stability",
    "freeze_manifest",
    "validate_wild_type_anchor",
]
