"""Render the post-cutoff antibody benchmark table into README.md.

    python scripts/update_readme_benchmark.py WORKDIR [--readme README.md]

Reads every WORKDIR/*.result.json written by benchmark_antibody_complexes.py and
replaces the text between the BENCH markers, so README numbers always come from
saved result files rather than being typed by hand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

START, END = "<!-- BENCH:START -->", "<!-- BENCH:END -->"
REFERENCE = Path("reports/boltz2-3hfm-reference-reproduction.json")


def _row(result: dict) -> str:
    if "scores" not in result:
        return (
            f"| {result['pdb_id']} | {result['released'][:7]} | n/a | n/a | n/a | n/a | n/a | "
            f"n/a | {result['verdict'].replace('_', ' ')} |"
        )
    s = result["scores"]
    return (
        f"| {result['pdb_id']} | {result['released'][:7]} | {result['model_confidence']:.2f} | "
        f"{s['antibody_rmsd_ca']:.1f} Å | {s['A_rmsd_ca']:.1f} Å | "
        f"{s['antigen_rmsd_in_antibody_frame_ca']:.1f} Å | "
        f"{round(100 * s['interface_recall'])}% | {_dockq(s)} | {result['verdict']} |"
    )


def _dockq(scores: dict) -> str:
    if "dockq" not in scores:
        return "n/a"
    return f"{scores['dockq']:.2f} ({scores['capri_class']})"


def render(workdir: Path, total: int) -> str:
    results = sorted(
        (json.loads(p.read_text()) for p in workdir.glob("*.result.json")),
        key=lambda r: r["pdb_id"],
    )
    ref = json.loads(REFERENCE.read_text())
    cmp = ref["comparison_to_crystal"]
    ok = sum(r["verdict"] == "success" for r in results)
    docked = sum(
        r.get("scores", {}).get("capri_class") not in (None, "incorrect") for r in results
    )
    lines = [
        "| PDB | Released | Model confidence | Antibody RMSD | Antigen alone | "
        "Antigen in antibody frame | Crystal contacts recovered | DockQ (CAPRI class) | "
        "Pre-registered rule |",
        "|---|---|---|---|---|---|---|---|---|",
        *(_row(r) for r in results),
        f"| 3HFM (reference) | 1989, pre-cutoff | {ref['prediction']['model_confidence']:.2f} | "
        f"{cmp['antibody_HL_rmsd_CA']:.1f} Å | {cmp['Y_rmsd_CA']:.1f} Å | "
        f"{cmp['antigen_rmsd_in_antibody_frame_CA']:.1f} Å | "
        f"{round(100 * cmp['interface_recall'])}% | "
        f"{_dockq(cmp.get('dockq_antibody_vs_antigen', {}))} | reference |",
        "",
        f"**{ok} of {len(results)} post-cutoff complexes met the pre-registered rule; "
        f"{docked} of {len(results)} are acceptable or better by DockQ"
        + (f" ({len(results)} of {total} run so far)." if len(results) < total else ".")
        + "**",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--total", type=int, default=9)
    args = parser.parse_args()
    text = args.readme.read_text()
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    args.readme.write_text(f"{head}{START}\n{render(args.workdir, args.total)}\n{END}{tail}")
    print("README benchmark table updated")


if __name__ == "__main__":
    main()
