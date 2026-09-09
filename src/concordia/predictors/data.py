"""Tox21 download, molecular validation, and duplicate handling."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

from concordia.artifacts import sha256_file


@dataclass(frozen=True)
class PreparedDataset:
    molecules: pd.DataFrame
    exclusions: pd.DataFrame


def download_file(url: str, destination: str | Path, expected_sha256: str | None) -> str:
    """Download atomically and return the file's SHA-256 digest."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url) as response, temporary.open("wb") as handle:
            while block := response.read(1024 * 1024):
                handle.write(block)
        digest = sha256_file(temporary)
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ValueError(
                f"Checksum mismatch for {url}: expected {expected_sha256}, got {digest}"
            )
        os.replace(temporary, target)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def canonicalize_smiles(smiles: str, include_chirality: bool = True) -> tuple[str, str]:
    """Return canonical SMILES and a Bemis–Murcko scaffold identifier."""
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError("RDKit could not parse SMILES")
    canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=include_chirality)
    scaffold = MurckoScaffold.MurckoScaffoldSmiles(
        mol=molecule, includeChirality=include_chirality
    )
    return canonical, scaffold


def prepare_tox21(
    path: str | Path, assay: str = "NR-AhR", include_chirality: bool = True
) -> PreparedDataset:
    """Validate labeled molecules and collapse canonical duplicates.

    Missing assay labels and invalid molecules are excluded. Canonical duplicates with
    consistent labels become one record; all members of a conflicting-label group are excluded.
    """
    source = pd.read_csv(path)
    required = {"smiles", assay}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    valid: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for row_id, row in source.iterrows():
        smiles = row["smiles"]
        label = row[assay]
        if pd.isna(label):
            excluded.append(
                {"source_row": int(row_id), "smiles": smiles, "reason": "missing_label"}
            )
            continue
        if float(label) not in (0.0, 1.0):
            excluded.append(
                {"source_row": int(row_id), "smiles": smiles, "reason": "non_binary_label"}
            )
            continue
        if not isinstance(smiles, str) or not smiles.strip():
            excluded.append(
                {"source_row": int(row_id), "smiles": smiles, "reason": "missing_smiles"}
            )
            continue
        try:
            canonical, scaffold = canonicalize_smiles(smiles, include_chirality)
        except ValueError:
            excluded.append(
                {"source_row": int(row_id), "smiles": smiles, "reason": "invalid_smiles"}
            )
            continue
        valid.append(
            {
                "source_row": int(row_id),
                "original_smiles": smiles,
                "canonical_smiles": canonical,
                "scaffold": scaffold,
                "label": int(label),
            }
        )

    valid_frame = pd.DataFrame(valid)
    records: list[dict[str, object]] = []
    for canonical, group in valid_frame.groupby("canonical_smiles", sort=True):
        labels = sorted(group["label"].unique().tolist())
        rows = sorted(int(value) for value in group["source_row"])
        if len(labels) != 1:
            for item in group.itertuples():
                excluded.append(
                    {
                        "source_row": int(item.source_row),
                        "smiles": item.original_smiles,
                        "reason": "conflicting_duplicate_labels",
                    }
                )
            continue
        first = group.sort_values("source_row").iloc[0]
        records.append(
            {
                "molecule_id": f"tox21:{rows[0]}",
                "source_rows": json.dumps(rows),
                "original_smiles": first["original_smiles"],
                "canonical_smiles": canonical,
                "scaffold": first["scaffold"],
                "label": labels[0],
                "duplicate_count": len(rows),
            }
        )

    molecules = pd.DataFrame(records).sort_values("molecule_id").reset_index(drop=True)
    exclusions = pd.DataFrame(excluded)
    if not exclusions.empty:
        exclusions = exclusions.sort_values("source_row").reset_index(drop=True)
    return PreparedDataset(molecules=molecules, exclusions=exclusions)
