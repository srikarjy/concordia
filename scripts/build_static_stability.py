"""Build the public stability bundle from verified, content-addressed inputs."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    (ROOT / "frontend/public/data/connectors.json").unlink(missing_ok=True)
    run("python3", "scripts/verify_static_stability_artifact.py")
    run("python3", "scripts/verify_review_replay.py")
    run("python3", "scripts/prepare_static_stability_payload.py")
    run("npm", "ci", cwd=ROOT / "frontend")
    run("npm", "run", "build:stability", cwd=ROOT / "frontend")
    run("python3", "scripts/sanitize_static_stability_bundle.py")


if __name__ == "__main__":
    main()
