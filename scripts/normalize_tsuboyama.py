"""Normalize the pinned Tsuboyama v2_230420 source into Concordia's schema.

The script is intentionally deterministic: it reads only the downloaded Zenodo
CSV, the accompanying quality table, and the bundled PDB files.  It emits one
row for each measured WT or single substitution that passes the documented
quality filters.  Concordia's convention is used at the boundary:
``deltaG_mut - deltaG_wt`` means higher ``ddg`` is more stable.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from Bio.PDB import PDBParser

SINGLE_MUTATION = re.compile(r"^[A-Z](\d+)[A-Z]$")
RAW_CORR_MIN = 0.80
DG_CORR_MIN = 0.80
FRAC_NA_MAX = 0.10
DISULFIDE_MAX_DISTANCE_ANGSTROM = 2.5


@dataclass(frozen=True)
class QualityRow:
    raw_corr: float
    dg_corr: float
    frac_na: float


def read_quality(path: Path) -> dict[str, QualityRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return {
            _required(row, "name", path): QualityRow(
                raw_corr=float(_required(row, "raw_corr", path)),
                dg_corr=float(_required(row, "dg_corr", path)),
                frac_na=float(_required(row, "frac_NA", path)),
            )
            for row in rows
        }


def quality_passes(row: QualityRow) -> bool:
    return (
        row.raw_corr >= RAW_CORR_MIN
        and row.dg_corr >= DG_CORR_MIN
        and row.frac_na <= FRAC_NA_MAX
    )


def read_structure_paths(path: Path) -> dict[str, Path]:
    return {candidate.name: candidate for candidate in path.glob("*.pdb")}


def disulfide_feature(path: Path) -> str:
    structure = PDBParser(QUIET=True).get_structure(path.stem, path)[0]
    cysteine_sulfur = [
        atom.coord
        for residue in structure.get_residues()
        if residue.get_resname().strip() == "CYS" and "SG" in residue
        for atom in [residue["SG"]]
    ]
    for index, left in enumerate(cysteine_sulfur):
        for right in cysteine_sulfur[index + 1 :]:
            if float(((left - right) ** 2).sum() ** 0.5) <= DISULFIDE_MAX_DISTANCE_ANGSTROM:
                return "disulfide_sg_sg"
    return ""


def _required(row: Mapping[str, str | None], field: str, path: Path) -> str:
    value = row[field]
    if value is None or not value.strip():
        raise ValueError(f"{path}: required field {field!r} is missing")
    return value.strip()


def _finite(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _position(mut_type: str) -> int:
    match = SINGLE_MUTATION.fullmatch(mut_type)
    if match is None:
        raise ValueError(f"not a single substitution: {mut_type!r}")
    return int(match.group(1))


def _single_rows(
    rows: Iterable[dict[str, str]], quality: dict[str, QualityRow]
) -> list[dict[str, object]]:
    by_domain: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        domain_id = _required(row, "WT_name", Path("Tsuboyama2023_Dataset2_Dataset3_20230416.csv"))
        by_domain[domain_id].append(row)

    normalized: list[dict[str, object]] = []
    for domain_id in sorted(by_domain):
        quality_row = quality.get(domain_id)
        if quality_row is None or not quality_passes(quality_row):
            continue
        domain_rows = by_domain[domain_id]
        wt_candidates = [row for row in domain_rows if row["name"] == domain_id]
        if not wt_candidates:
            continue
        wt = wt_candidates[0]
        wt_sequence = _required(wt, "aa_seq", Path("source"))
        wt_delta_g = _finite(wt.get("deltaG"))
        if wt_delta_g is None:
            continue
        normalized.append(_row(wt, domain_id, wt_sequence, wt_delta_g, 0, "", True))
        for row in domain_rows:
            mut_type = row.get("mut_type", "")
            if SINGLE_MUTATION.fullmatch(mut_type) is None:
                continue
            sequence = _required(row, "aa_seq", Path("source"))
            delta_g = _finite(row.get("deltaG"))
            if delta_g is None or len(sequence) != len(wt_sequence):
                continue
            position = _position(mut_type)
            if not 1 <= position <= len(wt_sequence):
                continue
            if sum(left != right for left, right in zip(sequence, wt_sequence, strict=True)) != 1:
                continue
            normalized.append(
                _row(row, domain_id, wt_sequence, wt_delta_g, position, mut_type, False)
            )
            normalized[-1]["ddg_kcal_higher_is_more_stable"] = delta_g - wt_delta_g
    return normalized


def _row(
    row: Mapping[str, str],
    domain_id: str,
    wt_sequence: str,
    wt_delta_g: float,
    position: int,
    mutation: str,
    is_wild_type: bool,
) -> dict[str, object]:
    delta_g = wt_delta_g if is_wild_type else float(row["deltaG"])
    return {
        "domain_id": domain_id,
        "sequence": row["aa_seq"],
        "wild_type_sequence": wt_sequence,
        "position": position,
        "variant_id": row["name"],
        "mutation_count": 0 if is_wild_type else 1,
        "delta_g_kcal_mol": delta_g,
        "ddg_kcal_higher_is_more_stable": 0.0 if is_wild_type else delta_g - wt_delta_g,
        "mutation": mutation or "wild_type",
        "structure_path": "",
        "hard_protection_feature": "",
        "is_wild_type": is_wild_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", type=Path, required=True)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--structures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    quality = read_quality(args.quality)
    structures = read_structure_paths(args.structures)
    with args.variants.open(newline="", encoding="utf-8") as handle:
        rows = _single_rows(csv.DictReader(handle), quality)
    features: dict[str, tuple[str, str]] = {}
    for domain_id in sorted({str(row["domain_id"]) for row in rows}):
        structure = structures.get(domain_id) or structures.get(
            f"{domain_id.replace('.pdb', '')}.pdb"
        )
        if structure is not None:
            features[domain_id] = (str(structure), disulfide_feature(structure))
    for row in rows:
        structure_path, hard_feature = features.get(str(row["domain_id"]), ("", ""))
        row["structure_path"] = structure_path
        row["hard_protection_feature"] = hard_feature
    fields = tuple(rows[0]) if rows else ()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"normalized_rows={len(rows)}")


if __name__ == "__main__":
    main()
