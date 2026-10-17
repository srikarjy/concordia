"""Safe logging/export redaction for campaign payloads."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "sequence",
        "target_sequence",
        "access_token",
        "raw_secret",
        "secret",
        "token",
        "authorization",
    }
)


def redact_for_log(value: Any) -> Any:
    """Recursively remove raw sequences and credentials from structured logs."""
    if isinstance(value, Mapping):
        return {str(key): _redacted_value(str(key), item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [redact_for_log(item) for item in value]
    return value


def _redacted_value(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_KEYS:
        raw = str(value).encode("utf-8")
        return {"redacted": True, "sha256": hashlib.sha256(raw).hexdigest()}
    return redact_for_log(value)


__all__ = ["SENSITIVE_KEYS", "redact_for_log"]
