from __future__ import annotations

import pytest
from pydantic import ValidationError

from concordia.antibody.schema import AntibodyDesignRequest, validate_antibody


def request() -> AntibodyDesignRequest:
    return AntibodyDesignRequest(
        chains=(
            {"chain_id": "H", "role": "heavy", "sequence": "EVQLVESGGGLVQPGGSLRLSCAAS"},
            {"chain_id": "L", "role": "light", "sequence": "DIQMTQSPSSLSASVGDRVTITC"},
        ),
        antigen_sequence="MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ",
        epitope_residues=(3, 1),
    )


def test_antibody_request_normalizes_sequences_and_epitope_positions() -> None:
    value = request()
    assert value.chains[0].sequence == "EVQLVESGGGLVQPGGSLRLSCAAS"
    assert value.epitope_residues == (1, 3)
    result = validate_antibody(value)
    assert result.chain_lengths == {"H": 25, "L": 23}
    assert result.scientific_use_allowed is False


@pytest.mark.parametrize(
    "override",
    [
        {"chains": ({"chain_id": "H", "role": "heavy", "sequence": "EVQLZ"},)},
        {"chains": ({"chain_id": "H", "role": "heavy", "sequence": "EVQLV"},)},
        {"antigen_sequence": "MKT", "epitope_residues": (3,)},
    ],
)
def test_antibody_request_rejects_invalid_design_inputs(override: dict[str, object]) -> None:
    values = request().model_dump()
    values.update(override)
    with pytest.raises(ValidationError):
        AntibodyDesignRequest.model_validate(values)


def test_nanobody_is_a_single_chain_design() -> None:
    value = AntibodyDesignRequest(
        chains=({"chain_id": "VHH", "role": "nanobody", "sequence": "EVQLVESGGGLVQPGGSLRLSCAAS"},),
        antigen_structure_artifact_digest="a" * 64,
    )
    assert value.chains[0].role == "nanobody"
