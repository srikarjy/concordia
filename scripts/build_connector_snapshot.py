"""Build the public, URL-free connector inventory from a recorded probe snapshot."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SOURCE = Path("scripts/nvidia_connector_probe_snapshot.json")
OUTPUT = Path("frontend/public/data/connectors.json")
STATES = {"healthy", "rate_limited", "unavailable", "unconfigured", "untested"}
URL_PATTERN = re.compile(r"https?://|/v1/|localhost|127\\.0\\.0\\.1|/Users/", re.I)


def build_snapshot(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("connector probe snapshot has no routes")
    public_routes: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            raise ValueError("connector route must be an object")
        required = {"name", "does", "state", "last_probed_at", "used_by_stability"}
        if set(route) != required:
            raise ValueError(f"connector route fields must be exactly {sorted(required)}")
        if route["state"] not in STATES:
            raise ValueError(f"unknown connector state: {route['state']}")
        if URL_PATTERN.search(json.dumps(route, sort_keys=True)):
            raise ValueError("connector snapshot contains an endpoint or local path")
        public_routes.append(dict(route))
    result = {
        "schema_version": payload["schema_version"],
        "snapshot_recorded_at": payload["snapshot_recorded_at"],
        "source": payload.get("source", "recorded probe results"),
        "raw_probe_artifact_present": bool(payload.get("raw_probe_artifact_present", True)),
        "live_health": False,
        "routes": public_routes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = build_snapshot()
    print(f"connector snapshot built: {len(result['routes'])} routes")


if __name__ == "__main__":
    main()
