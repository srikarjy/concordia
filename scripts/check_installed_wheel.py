"""Smoke-test a non-editable wheel outside the source checkout, without inference.

Run using the wheel environment's Python from a temporary working directory.
The project package must resolve inside that environment, not the source tree.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


def main() -> None:
    from fastapi.testclient import TestClient

    import concordia
    from concordia.api.workspace import create_workspace_app

    installed = Path(concordia.__file__).resolve()
    if not installed.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(f"expected an installed wheel, found {installed}")
    if importlib.util.find_spec("Bio") is None:
        raise RuntimeError("required Biopython runtime dependency is missing")
    with tempfile.TemporaryDirectory(prefix="concordia-wheel-smoke-") as state:
        app = create_workspace_app(Path(state))
        with TestClient(
            app, base_url="http://localhost", client=("127.0.0.1", 12345)
        ) as client:
            example = client.get("/api/reviews/example")
            example.raise_for_status()
            created = client.post("/api/reviews", json=example.json()["input"])
            created.raise_for_status()
            review = created.json()["review"]
            exported = client.get(
                f"/api/reviews/{review['review_id']}/export/zip?revision={review['revision']}"
            )
            exported.raise_for_status()
            if not exported.content.startswith(b"PK"):
                raise RuntimeError("review export did not return a ZIP bundle")
    print(f"Installed wheel review/example/export passed: {installed}")


if __name__ == "__main__":
    main()
