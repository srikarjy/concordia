"""Create frozen packets from baseline and explanation artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from concordia.evidence.packets import packet_from_row, write_packet


def build_packets(
    molecules_path: str | Path,
    shap_values_path: str | Path,
    output_directory: str | Path,
    limit: int | None = None,
) -> dict[str, int | str]:
    molecules = pd.read_csv(molecules_path).sort_values("molecule_id").reset_index(drop=True)
    values = np.load(shap_values_path, allow_pickle=False)
    if len(molecules) != len(values):
        if limit is None or len(values) != min(limit, len(molecules)):
            raise ValueError("Molecule rows and SHAP rows must have identical lengths")
        molecules = molecules.head(len(values)).copy()
    if limit is not None:
        molecules = molecules.head(limit).copy()
        values = values[: len(molecules)]
    if values.ndim != 2 or len(molecules) != len(values):
        raise ValueError("SHAP artifact must be a two-dimensional matrix aligned to molecules")

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.jsonl"
    with index_path.open("w", encoding="utf-8") as handle:
        for row_index, (_, row) in enumerate(molecules.iterrows()):
            packet = packet_from_row(
                row,
                values[row_index],
                shap_version="recorded_tree_shap",
            )
            packet_path = write_packet(packet, output / "packets")
            handle.write(
                json.dumps(
                    {
                        "molecule_id": packet.molecule_id,
                        "packet_hash": packet.content_hash(),
                        "path": str(packet_path.relative_to(output)),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return {"output_directory": str(output), "packet_count": len(molecules)}
