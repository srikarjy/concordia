"""Remove unused Mol* service defaults from the public static bundle."""

from __future__ import annotations

from pathlib import Path

DIST = Path("frontend/dist-stability")
FORBIDDEN_DEFAULTS = {
    "https://webchem.ncbr.muni.cz/molstar-state": "",
    "https://ds.litemol.org": "",
}


def main() -> None:
    changed = 0
    for path in DIST.rglob("*"):
        if not path.is_file() or path.suffix not in {".js", ".css", ".html"}:
            continue
        original = path.read_text()
        sanitized = original
        for source, replacement in FORBIDDEN_DEFAULTS.items():
            sanitized = sanitized.replace(source, replacement)
        if sanitized != original:
            path.write_text(sanitized)
            changed += 1
    print(f"static bundle sanitized: {changed} files")


if __name__ == "__main__":
    main()
