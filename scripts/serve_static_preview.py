"""Preview the public bundle with the repository's static rewrites and headers.

This is a loopback-only test server, not a Vercel emulator or production server.
Only exact static rewrites are supported; absent API endpoints return 404.
"""

from __future__ import annotations

import argparse
import json
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class StaticPreviewHandler(SimpleHTTPRequestHandler):
    config: dict[str, Any] = {}

    def do_GET(self) -> None:
        self._rewrite()
        super().do_GET()

    def do_HEAD(self) -> None:
        self._rewrite()
        super().do_HEAD()

    def _rewrite(self) -> None:
        path = urlsplit(self.path).path
        for rule in self.config.get("rewrites", []):
            if path == rule["source"]:
                self.path = rule["destination"]
                break

    def end_headers(self) -> None:
        path = urlsplit(self.path).path
        for rule in self.config.get("headers", []):
            if re.fullmatch(rule["source"], path):
                for header in rule["headers"]:
                    self.send_header(header["key"], header["value"])
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--config", type=Path, default=Path("vercel.json"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    root = args.config.resolve().parent / config["outputDirectory"]
    if not (root / "index.html").is_file() or not (root / "stability.html").is_file():
        parser.error(f"public review/stability bundle missing at {root}; build it first")
    StaticPreviewHandler.config = config
    with ThreadingHTTPServer(
        ("127.0.0.1", args.port), partial(StaticPreviewHandler, directory=str(root))
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
