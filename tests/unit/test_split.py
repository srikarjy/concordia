import pandas as pd

from concordia.config import SplitConfig
from concordia.predictors.split import scaffold_split


def test_scaffold_split_is_deterministic_and_group_safe() -> None:
    frame = pd.DataFrame(
        {
            "canonical_smiles": [f"molecule-{index}" for index in range(18)],
            "scaffold": [f"s{index // 2}" for index in range(18)],
            "label": [index % 2 for index in range(18)],
        }
    )
    config = SplitConfig(1729, 0.7, 0.15, 0.15)

    first = scaffold_split(frame, config)
    second = scaffold_split(frame, config)

    assert first["split"].tolist() == second["split"].tolist()
    assert first.groupby("scaffold")["split"].nunique().max() == 1
    assert set(first["split"]) == {"train", "validation", "test"}
