import numpy as np
import pandas as pd
import pytest

from concordia.evidence.packets import packet_from_row
from concordia.interventions.transform import corrupt_sign, shuffle, withhold


def _packet(molecule_id: str = "tox21:1"):
    row = pd.Series(
        {
            "molecule_id": molecule_id,
            "canonical_smiles": "CCO",
            "model_id": "rf-test",
            "assay": "NR-AhR",
            "prediction_probability": 0.75,
            "prediction": 1,
        }
    )
    return packet_from_row(row, np.array([0.2, -0.1, 0.0]), shap_version="test")


def test_packet_hash_and_interventions_are_deterministic() -> None:
    packet = _packet()
    assert packet.content_hash() == packet.content_hash()
    assert withhold(packet).packet.explanation is None
    shuffled = shuffle(packet, _packet("tox21:2"))
    assert shuffled.packet.molecule_id == packet.molecule_id
    assert shuffled.donor_hash is not None
    first = corrupt_sign(packet, seed=7, fraction=1).packet
    second = corrupt_sign(packet, seed=7, fraction=1).packet
    assert first == second
    assert first.explanation.top_positive != packet.explanation.top_positive


def test_shuffle_rejects_self_donor_and_withheld_donor() -> None:
    packet = _packet()
    with pytest.raises(ValueError, match="differ"):
        shuffle(packet, packet)
    with pytest.raises(ValueError, match="explanation"):
        shuffle(packet, withhold(packet).packet)
