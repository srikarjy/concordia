import numpy as np
import pandas as pd

from concordia.evidence.packets import packet_from_row
from concordia.scientist.ollama import ScientistGeneration
from concordia.scientist.records import ScientistRunRecord, read_record, write_record
from concordia.scientist.schema import ScientistResponse


def test_scientist_record_round_trip(tmp_path) -> None:
    packet = packet_from_row(
        pd.Series(
            {
                "molecule_id": "tox21:record",
                "canonical_smiles": "CCO",
                "model_id": "rf-test",
                "assay": "NR-AhR",
                "prediction_probability": 0.75,
                "prediction": 1,
            }
        ),
        np.array([0.2, -0.1]),
    )
    response = ScientistResponse(summary="bounded", claims=[])
    generation = ScientistGeneration(
        raw_response=response.model_dump_json(),
        parsed=response,
        metadata={"runtime": "test", "temperature": 0.0},
    )
    record = ScientistRunRecord.from_generation(packet, "control", "test-model", generation)
    path = write_record(record, tmp_path)
    assert read_record(path) == record
    assert record.packet_hash == packet.content_hash()
    assert record.messages[0]["role"] == "system"
