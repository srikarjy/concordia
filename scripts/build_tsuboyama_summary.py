"""Build a deterministic domain summary from a normalized Tsuboyama CSV."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NormalizedVariant:
    domain_id: str
    sequence: str
    position: int
    variant_id: str
    mutation_count: int
    structure_path: str
    hard_protection_feature: str
    is_wild_type: bool


def read_variants(path: Path) -> list[NormalizedVariant]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "domain_id",
            "sequence",
            "position",
            "variant_id",
            "mutation_count",
            "structure_path",
            "hard_protection_feature",
        }
        _require_columns(reader.fieldnames, required, path)
        return [_parse_row(row, path) for row in reader]


def _parse_row(row: Mapping[str, str | None], path: Path) -> NormalizedVariant:
    domain_id = _required(row, "domain_id", path)
    sequence = "".join(_required(row, "sequence", path).upper().split())
    variant_id = _required(row, "variant_id", path)
    position = _parse_int(_required(row, "position", path), "position", variant_id)
    mutation_count = _parse_int(
        _required(row, "mutation_count", path), "mutation_count", variant_id
    )
    structure_path = _required(row, "structure_path", path)
    hard_feature = _required(row, "hard_protection_feature", path)
    raw_wild_type = row.get("is_wild_type")
    is_wild_type = raw_wild_type is not None and raw_wild_type.strip().lower() == "true"
    return NormalizedVariant(
        domain_id=domain_id,
        sequence=sequence,
        position=position,
        variant_id=variant_id,
        mutation_count=mutation_count,
        structure_path=structure_path,
        hard_protection_feature=hard_feature,
        is_wild_type=is_wild_type,
    )


def _required(row: Mapping[str, str | None], field: str, path: Path) -> str:
    value = row[field]
    if value is None or not value.strip():
        raise ValueError(f"{path}: required field {field!r} is missing")
    return value.strip()


def _parse_int(value: str, field: str, variant_id: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"variant {variant_id!r} has an invalid {field}") from error


def _require_columns(fieldnames: Sequence[str] | None, required: set[str], path: Path) -> None:
    missing = sorted(required - set(fieldnames or []))
    if missing:
        raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = read_variants(args.variants)
    grouped: dict[str, list[NormalizedVariant]] = defaultdict(list)
    for row in rows:
        grouped[row.domain_id].append(row)
    output: list[dict[str, str]] = []
    for domain_id in sorted(grouped):
        domain_rows = grouped[domain_id]
        wild_type = next((row for row in domain_rows if row.is_wild_type), None)
        representative = wild_type or min(domain_rows, key=lambda row: row.sequence)
        hard_features = sorted(
            {row.hard_protection_feature for row in domain_rows if row.hard_protection_feature}
        )
        output.append(
            {
                "domain_id": domain_id,
                "sequence": representative.sequence,
                "length": str(len(representative.sequence)),
                "single_substitution_count": str(
                    sum(row.mutation_count == 1 for row in domain_rows)
                ),
                "structure_path": representative.structure_path,
                "hard_protection_feature": ";".join(hard_features),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "domain_id",
        "sequence",
        "length",
        "single_substitution_count",
        "structure_path",
        "hard_protection_feature",
    )
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)


if __name__ == "__main__":
    main()
