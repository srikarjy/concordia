"""Small helpers for content-addressed research artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import rdkit
import sklearn


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def environment_metadata() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "rdkit": rdkit.__version__,
        "scikit_learn": sklearn.__version__,
    }


def git_metadata() -> dict[str, str | bool | None]:
    def run(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    status = run("status", "--porcelain")
    return {
        "revision": run("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def command_metadata() -> dict[str, Any]:
    return {"argv": sys.argv, "cwd": str(Path.cwd())}
