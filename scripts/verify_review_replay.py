"""Verify all published replay revisions without installing Concordia."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    replay = ROOT / "frontend/public/review-replay"
    revisions = json.loads((replay / "review.json").read_text())["revisions"]
    for item in revisions:
        review = item["review"]
        prefix = f"r{review['revision']}"
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            with zipfile.ZipFile(replay / f"{prefix}-bundle.zip") as archive:
                archive.extractall(target)
            subprocess.run([sys.executable, "-I", "verify.py"], cwd=target, check=True)
            if json.loads((target / "review.json").read_text()) != review:
                raise ValueError(f"{prefix}: displayed snapshot differs from export")
            for outer, inner in [("selected.csv", "selected-candidates.csv"),
                                 ("decisions.csv", "all-decisions.csv"),
                                 ("report.html", "report.html")]:
                if (replay / f"{prefix}-{outer}").read_bytes() != (target / inner).read_bytes():
                    raise ValueError(f"{prefix}: displayed export differs: {outer}")
    print(f"Verified {len(revisions)} replay revisions and their standalone exports")
    public = ROOT / "frontend/public/public-data-review"
    raw = (public / "bundle.zip").read_bytes()
    if hashlib.sha256(raw).hexdigest() != (public / "bundle.zip.sha256").read_text().strip():
        raise ValueError("Public data bundle checksum mismatch")
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary)
        with zipfile.ZipFile(public / "bundle.zip") as archive:
            archive.extractall(target)
        subprocess.run([sys.executable, "-I", "verify.py"], cwd=target, check=True)
        for outer, inner in [("execution.json", "diagnostics/execution.json"),
                             ("measured-dataset.csv", "diagnostics/measured-dataset.csv"),
                             ("review.html", "report.html")]:
            if (public / outer).read_bytes() != (target / inner).read_bytes():
                raise ValueError(f"Public data artifact differs from bundle: {outer}")
    print("Verified public measured-data execution and exports")


if __name__ == "__main__":
    main()
