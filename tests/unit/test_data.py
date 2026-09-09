from pathlib import Path

import pandas as pd

from concordia.predictors.data import prepare_tox21


def test_prepare_tox21_filters_and_collapses_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "tox21.csv"
    pd.DataFrame(
        {
            "smiles": ["CCO", "OCC", "c1ccccc1", "bad smiles", "CCN", "CCN", "CCC"],
            "NR-AhR": [0, 0, 1, 0, 0, 1, None],
        }
    ).to_csv(path, index=False)

    prepared = prepare_tox21(path)

    assert set(prepared.molecules["canonical_smiles"]) == {"CCO", "c1ccccc1"}
    ethanol = prepared.molecules.loc[prepared.molecules["canonical_smiles"] == "CCO"].iloc[0]
    assert ethanol["duplicate_count"] == 2
    assert set(prepared.exclusions["reason"]) == {
        "invalid_smiles",
        "conflicting_duplicate_labels",
        "missing_label",
    }
