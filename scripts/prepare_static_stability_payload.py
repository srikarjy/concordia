"""Materialize the verified stability report at its content-addressed URL."""

from __future__ import annotations

import shutil
from pathlib import Path

from verify_static_stability_artifact import verify_artifact

SOURCE = Path("frontend/public/data/stability.json")
DATA_DIR = SOURCE.parent


def main() -> None:
    report = verify_artifact(SOURCE)
    digest = report["artifact_digest"]
    destination = DATA_DIR / f"{digest}.json"
    shutil.copyfile(SOURCE, destination)
    print(f"static stability payload prepared: {destination}")


if __name__ == "__main__":
    main()
