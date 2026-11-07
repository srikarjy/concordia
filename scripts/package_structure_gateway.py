"""Package only the small gateway and its existing shared runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "__init__.py",
    "genomics/__init__.py",
    "genomics/boltz_nvidia.py",
    "genomics/boltz_gateway.py",
    "genomics/rate_limiting.py",
    "storage/__init__.py",
    "storage/content.py",
    "events/__init__.py",
    "events/sqlite.py",
    "runtime/__init__.py",
    "runtime/contracts.py",
    "runtime/structure_workflow.py",
)


def package(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for name in ("Dockerfile", "README.md", "app.py", "requirements.lock.txt"):
        shutil.copyfile(ROOT / "deploy/hf-structure-gateway" / name, destination / name)
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE")
    for name in FILES:
        target = destination / "src/concordia" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/concordia" / name, target)
    manifest_path = ROOT / "data/manifests/tsuboyama_rule2_manifest_v3.json"
    manifest_bytes = manifest_path.read_bytes()
    if (
        hashlib.sha256(manifest_bytes).hexdigest()
        != "ee683066419099303046a16e799f7eb21d88963cdd83d8c08e28587d0faedafc"
    ):
        raise ValueError("Frozen manifest file digest changed")
    manifest = json.loads(manifest_bytes)
    pdb = ROOT / "frontend/public/data/structure/1IGV.pdb"
    names = dict(
        zip(
            (
                "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL"
            ).split(),
            "ARNDCQEGHILKMFPSTWYV",
            strict=True,
        )
    )
    residues = {}
    for line in pdb.read_text().splitlines():
        if line.startswith("ATOM  ") and line[21] == "A" and line[12:16].strip() == "CA":
            position = int(line[22:26])
            if position in residues or line[26] != " ":
                raise ValueError("Ambiguous structure residue numbering")
            residues[position] = names[line[17:20]]
    length = int(manifest["selection"]["length"])
    if sorted(residues) != list(range(1, length + 1)):
        raise ValueError("PDB does not match manifest position range")
    for protected in manifest["selection"]["hard_protected_residues"]:
        if residues[protected["local_position"]] != protected["local_residue"]:
            raise ValueError("Protected residue does not match frozen manifest")
    (destination / "domain.json").write_text(
        json.dumps(
            {
                "sequence": "".join(residues[i] for i in range(1, length + 1)),
                "manifest_digest": manifest["manifest_digest"],
                "structure_sha256": hashlib.sha256(pdb.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    total = 0
    for path in destination.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            total += len(data)
            if re.search(rb"nvapi-|hf_[A-Za-z0-9]{20,}|/Users/|sk-[A-Za-z0-9]{20,}", data):
                raise ValueError(f"Secret/local path pattern in {path.relative_to(destination)}")
    print(json.dumps({"packaged_bytes": total, "secret_scan": "passed"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    package(parser.parse_args().destination)


if __name__ == "__main__":
    main()
