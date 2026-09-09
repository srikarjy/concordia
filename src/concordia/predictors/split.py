"""Deterministic group-aware splitting for molecular data."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from concordia.config import SplitConfig


def scaffold_split(frame: pd.DataFrame, config: SplitConfig) -> pd.DataFrame:
    """Assign complete scaffold groups to deterministic train/validation/test splits."""
    if frame.empty:
        raise ValueError("Cannot split an empty dataset")
    required = {"scaffold", "label", "canonical_smiles"}
    if missing := required.difference(frame.columns):
        raise ValueError(f"Cannot split without columns: {sorted(missing)}")

    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in frame.iterrows():
        # Ring-free molecules share the empty Murcko scaffold. Keeping them together is
        # conservative and prevents a nominal scaffold split from leaking this group.
        groups[str(row["scaffold"])].append(int(index))

    rng = np.random.default_rng(config.seed)
    sortable = []
    for scaffold, indices in groups.items():
        sortable.append((len(indices), float(rng.random()), scaffold, indices))
    sortable.sort(key=lambda item: (-item[0], item[1], item[2]))

    train_cutoff = config.train_fraction * len(frame)
    validation_cutoff = (config.train_fraction + config.validation_fraction) * len(frame)
    assigned_train = 0
    assigned_validation = 0
    assignments: dict[int, str] = {}

    for _, _, _, indices in sortable:
        if assigned_train + len(indices) <= train_cutoff:
            destination = "train"
            assigned_train += len(indices)
        elif assigned_train + assigned_validation + len(indices) <= validation_cutoff:
            destination = "validation"
            assigned_validation += len(indices)
        else:
            destination = "test"
        for index in indices:
            assignments[index] = destination

    result = frame.copy()
    result["split"] = pd.Series(assignments)
    _validate_split(result)
    return result


def _validate_split(frame: pd.DataFrame) -> None:
    if frame["split"].isna().any():
        raise ValueError("Some molecules were not assigned to a split")
    scaffold_counts = frame.groupby("scaffold")["split"].nunique()
    if (scaffold_counts > 1).any():
        raise ValueError("A scaffold group crosses split boundaries")
    if set(frame["split"]) != {"train", "validation", "test"}:
        raise ValueError("All three splits must contain at least one molecule")
