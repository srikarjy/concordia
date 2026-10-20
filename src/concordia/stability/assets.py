"""Trusted byte identities for the frozen 1IGV serving inputs.

The manifest is an approval of known local bytes, not an external attestation or
a license to redistribute the underlying data/model files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ASSET_MANIFEST_NAME = "data/manifests/tsuboyama_stability_assets_v1.json"
TRUSTED_MANIFEST_SHA256 = "18ad2cc7ebc4aa36e18c43a759f896bd8e490b25cde33e9c70b2b4f0f7df3971"
DEFAULT_ASSET_ROOT = Path(__file__).resolve().parents[3]


def resolve_asset_root(root: Path | None = None) -> Path:
    chosen = root or Path(os.environ.get("CONCORDIA_STABILITY_ASSET_ROOT", DEFAULT_ASSET_ROOT))
    return chosen.expanduser().resolve()


def load_trusted_manifest(root: Path) -> dict[str, Any]:
    path = root / ASSET_MANIFEST_NAME
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRUSTED_MANIFEST_SHA256:
        raise ValueError("frozen stability asset manifest differs from the pinned version")
    payload = json.loads(raw)
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "concordia_frozen_1igv_serving_assets"
    ):
        raise ValueError("unexpected frozen stability asset manifest schema")
    return payload


def verify_assets(root: Path, *, include_calibration: bool = True) -> dict[str, Any]:
    """Verify all declared bytes before opening any serialized Python object."""
    manifest = load_trusted_manifest(root)
    calibration = "data/processed/tsuboyama_t2_recalibration.json"
    for name, record in manifest["files"].items():
        if name == calibration and not include_calibration:
            continue
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid asset path in manifest: {name}")
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"frozen stability asset missing: {name}")
        if path.stat().st_size != record["size_bytes"]:
            raise ValueError(f"frozen stability asset size mismatch: {name}")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"frozen stability asset digest mismatch: {name}")
    return manifest
