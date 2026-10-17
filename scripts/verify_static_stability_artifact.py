"""Verify the immutable payload consumed by the static stability page."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

EXPECTED_DIGEST = "dae4e417463b959e68b7ab2f25d4475e46e0be8d63d7af4c9c42bf1e78540b00"
DEFAULT_ARTIFACT = Path("frontend/public/data/stability.json")
_FORBIDDEN = re.compile(
    r"(?:NVIDIA_API_KEY|nvapi-[A-Za-z0-9_-]{20,}|127\\.0\\.0\\.1|localhost|/Users/)",
    re.I,
)


def payload_digest(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("artifact_digest", None)
    payload.pop("run_id", None)
    payload.pop("ledger_intact", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_artifact(path: Path = DEFAULT_ARTIFACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("static stability artifact must be a JSON object")
    recorded = value.get("artifact_digest")
    if recorded != EXPECTED_DIGEST or payload_digest(value) != EXPECTED_DIGEST:
        raise ValueError("static stability artifact digest does not match the preregistered digest")
    structure = value.get("structure")
    if not isinstance(structure, dict) or structure.get("path") != "structure/1IGV.pdb":
        raise ValueError("artifact must reference the bundled 1IGV structure")
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN.search(serialized):
        raise ValueError("static artifact contains a secret or internal/local endpoint")
    return value


def main() -> None:
    checked = verify_artifact()
    print(f"static artifact verified: {checked['artifact_digest']}")


if __name__ == "__main__":
    main()
