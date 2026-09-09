"""Content-addressed local artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class ContentAddressedStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put_bytes(self, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        path = self.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        return digest

    def put_json(self, value: Any) -> str:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return self.put_bytes(payload)

    def get_bytes(self, digest: str) -> bytes:
        payload = self.path_for(digest).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("artifact hash does not match requested hash")
        return payload

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("artifact digest must be lowercase SHA-256")
        return self.root / "sha256" / digest[:2] / digest
