"""Select and freeze the first qualifying Tsuboyama stability domain.

The input is a reviewed domain summary CSV. It intentionally does not inspect
labels before splitting; the selected domain and split membership are frozen in
one manifest before embedding extraction begins.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from concordia.stability.contracts import (
    INTERNAL_STABILITY_DDG_CONVENTION,
    canonical_json,
    freeze_manifest,
)


@dataclass(frozen=True)
class SummaryRow:
    domain_id: str
    sequence: str
    length: int
    single_substitution_count: int
    structure_path: str
    hard_protection_feature: str


@dataclass(frozen=True)
class VariantRow:
    domain_id: str
    position: int
    variant_id: str
    values: dict[str, object]


def select_domain(rows: Sequence[SummaryRow]) -> SummaryRow:
    for row in sorted(rows, key=lambda item: item.domain_id):
        if (
            row.single_substitution_count >= 1000
            and 50 <= row.length <= 80
            and row.structure_path
            and row.hard_protection_feature
        ):
            return row
    raise ValueError("no domain satisfies the frozen selection criteria")


def parse_variant_row(row: Mapping[str, object]) -> VariantRow:
    domain_id = _required_text(row, "domain_id")
    variant_id = _required_text(row, "variant_id")
    position_value = row["position"]
    try:
        position = int(cast(Any, position_value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"variant {variant_id!r} has an invalid position") from error
    values = dict(row)
    values["domain_id"] = domain_id
    values["variant_id"] = variant_id
    values["position"] = position
    return VariantRow(domain_id=domain_id, position=position, variant_id=variant_id, values=values)


def filtered_variant_digest(rows: Sequence[VariantRow], domain_id: str) -> str:
    canonical = canonical_json(canonical_variant_payload(rows, domain_id))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_variant_payload(rows: Sequence[VariantRow], domain_id: str) -> dict[str, object]:
    filtered = sorted(
        (row for row in rows if row.domain_id == domain_id),
        key=lambda row: (row.position, row.variant_id),
    )
    return {"domain_id": domain_id, "rows": [row.values for row in filtered]}


def read_summary_rows(path: Path) -> list[SummaryRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "domain_id",
            "sequence",
            "length",
            "single_substitution_count",
            "structure_path",
            "hard_protection_feature",
        }
        _require_columns(reader.fieldnames, required, path)
        return [
            SummaryRow(
                domain_id=_required_csv(row, "domain_id", path),
                sequence=_required_csv(row, "sequence", path),
                length=int(_required_csv(row, "length", path)),
                single_substitution_count=int(
                    _required_csv(row, "single_substitution_count", path)
                ),
                structure_path=_required_csv(row, "structure_path", path),
                hard_protection_feature=_required_csv(row, "hard_protection_feature", path),
            )
            for row in reader
        ]


def read_variant_rows(path: Path) -> list[VariantRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, {"domain_id", "position", "variant_id"}, path)
        return [
            parse_variant_row({key: value for key, value in row.items() if value is not None})
            for row in reader
        ]


def _required_text(row: Mapping[str, object], field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"required field {field!r} is missing")
    return value.strip()


def _required_csv(row: Mapping[str, str | None], field: str, path: Path) -> str:
    value = row[field]
    if value is None or not value.strip():
        raise ValueError(f"{path}: required field {field!r} is missing")
    return value.strip()


def _require_columns(fieldnames: Sequence[str] | None, required: set[str], path: Path) -> None:
    fields = set(fieldnames or [])
    missing = sorted(required - fields)
    if missing:
        raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument("--variant-table", type=Path, required=True)
    parser.add_argument("--raw-zenodo-file", type=Path, required=True)
    parser.add_argument("--normalization-command", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-version", default="zenodo-v2_230420")
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args()
    selected = select_domain(read_summary_rows(args.summary_csv))
    positions: dict[str, list[str]] = {str(index): [] for index in range(5)}
    variant_rows = read_variant_rows(args.variant_table)
    variant_hash = filtered_variant_digest(variant_rows, selected.domain_id)
    domain_rows = [row for row in variant_rows if row.domain_id == selected.domain_id]
    for row in domain_rows:
        positions[str(row.position % 5)].append(row.variant_id)
    payload = {
        "kind": "concordia_tsuboyama_stability_manifest",
        "source": {
            "dataset": "Tsuboyama_2023_megascale",
            "version": args.source_version,
            "concept_doi": "10.5281/zenodo.7992926",
            "license": "CC-BY-4.0",
            "raw_zenodo_file_sha256": hashlib.sha256(args.raw_zenodo_file.read_bytes()).hexdigest(),
            "normalization_command": args.normalization_command,
        },
        "domain": {
            "domain_id": selected.domain_id,
            "sequence": selected.sequence,
            "length": selected.length,
            "single_substitution_count": selected.single_substitution_count,
            "structure_path": selected.structure_path,
            "hard_protection_feature": selected.hard_protection_feature,
        },
        "label": {
            "field": "ddg_kcal_higher_is_more_stable",
            "source_field": "delta_g_kcal_mol",
            "definition": "delta_g_mutant_minus_delta_g_wild_type",
            "sign_convention": INTERNAL_STABILITY_DDG_CONVENTION,
            "wild_type_anchor": 0.0,
        },
        "filters": {
            "minimum_single_substitutions": 1000,
            "length_range": [50, 80],
            "requires_structure": True,
            "requires_hard_protection_feature": True,
        },
        "split": {
            "primary": "position_modulo_5",
            "diagnostic": ["position_contiguous_5", "random_5"],
            "seed": args.seed,
            "holdout_frozen_before_embeddings": True,
            "fold_membership": {
                "modulo_5": {fold: sorted(values) for fold, values in positions.items()}
            },
        },
        "filtered_variant_table_sha256": variant_hash,
        "filtered_variant_row_count": len(domain_rows),
        "status": "frozen_before_embeddings",
        "scientific_use_allowed": False,
    }
    manifest = freeze_manifest(payload, args.output)
    print(
        json.dumps({"domain_id": selected.domain_id, "manifest_digest": manifest.manifest_digest})
    )


if __name__ == "__main__":
    main()
