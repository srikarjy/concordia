"""Create a verified local archive of the frozen 1IGV serving inputs.

The archive is deliberately not committed. It is a release artifact that must be
published only after its data-license and hosting destination are reviewed.
"""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

from concordia.stability.assets import ASSET_MANIFEST_NAME, resolve_asset_root, verify_assets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_root = resolve_asset_root(args.source_root)
    manifest = verify_assets(source_root)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        archive.add(source_root / ASSET_MANIFEST_NAME, arcname=ASSET_MANIFEST_NAME)
        for name in sorted(manifest["files"]):
            archive.add(source_root / name, arcname=name)
    print(f"verified frozen stability archive written: {output}")


if __name__ == "__main__":
    main()
