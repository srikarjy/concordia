from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_connector_snapshot import build_snapshot


def test_connector_snapshot_is_public_and_url_free(tmp_path: Path) -> None:
    output = tmp_path / "connectors.json"
    result = build_snapshot(output=output)
    assert result["live_health"] is False
    assert len(result["routes"]) == 13
    assert all("http" not in json.dumps(route).lower() for route in result["routes"])
    assert sum(route["used_by_stability"] for route in result["routes"]) == 1


def test_connector_snapshot_rejects_endpoint_urls(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    payload = json.loads(Path("scripts/nvidia_connector_probe_snapshot.json").read_text())
    payload["routes"][0]["does"] = "call https://example.test"
    source.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="endpoint"):
        build_snapshot(source=source, output=tmp_path / "out.json")
