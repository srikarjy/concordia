"""Local credential loading with a strict no-logging boundary."""

from __future__ import annotations

import os
from pathlib import Path


def nvidia_api_key(root: Path = Path(".")) -> str | None:
    """Read NVIDIA_API_KEY first, then the local 0600 fallback file."""
    value = os.environ.get("NVIDIA_API_KEY", "").strip()
    if value:
        return value
    path = root / ".concordia" / "nvidia-api-key"
    if not path.is_file():
        return None
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise RuntimeError("local NVIDIA API key file must have mode 0600")
    value = path.read_text(encoding="utf-8").strip()
    return value or None


__all__ = ["nvidia_api_key"]
