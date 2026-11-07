"""Fail early when any frozen 1IGV serving asset is absent.

This checks availability only. ``verify_assets`` performs the digest check before
serving deserializes a model. It must not generate replacements or skip tests.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ASSET_MANIFEST = Path("data/manifests/tsuboyama_stability_assets_v1.json")


def missing_assets(root: Path) -> list[str]:
    manifest_path = root / ASSET_MANIFEST
    if not manifest_path.is_file():
        return [str(ASSET_MANIFEST)]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = payload["files"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return [f"{ASSET_MANIFEST} (invalid manifest)"]
    if not isinstance(files, dict):
        return [f"{ASSET_MANIFEST} (invalid files map)"]
    return [name for name in sorted(files) if not (root / name).is_file()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    missing = missing_assets(args.root)
    if missing:
        parser.exit(
            1,
            "Frozen 1IGV regression prerequisites are missing:\n"
            + "\n".join(f"  {name}" for name in missing)
            + "\nSee docs/installation-and-checks.md for the verified asset bundle. "
            "No model retraining or test skipping is implied.\n",
        )
    print("All frozen 1IGV serving inputs are present (availability only, not integrity).")


if __name__ == "__main__":
    main()
