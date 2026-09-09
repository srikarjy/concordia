import numpy as np
import pandas as pd

from concordia.evidence.packets import packet_from_row
from concordia.scientist.tools import (
    ToolGateway,
    ToolPolicy,
    ToolRequest,
    register_read_only_tools,
)


def _packet():
    return packet_from_row(
        pd.Series(
            {
                "molecule_id": "tox21:tool",
                "canonical_smiles": "CCO",
                "model_id": "rf-test",
                "assay": "NR-AhR",
                "prediction_probability": 0.75,
                "prediction": 1,
            }
        ),
        np.array([0.2, -0.1]),
    )


def test_gateway_enforces_policy_and_records_trace() -> None:
    gateway = ToolGateway(
        ToolPolicy(
            policy_version="test",
            mode="evaluation",
            allowed_tools=frozenset({"evidence.packet_summary"}),
            max_tool_calls=1,
        ),
        _packet(),
    )
    register_read_only_tools(gateway)
    request = ToolRequest(request_id="r1", tool="evidence.packet_summary", reason="inspect packet")
    result = gateway.call(request)
    assert result.status == "success"
    assert result.result["packet_hash"] == gateway.packet.content_hash()
    denied = gateway.call(
        ToolRequest(request_id="r2", tool="rdkit.describe_molecule", reason="inspect structure")
    )
    assert denied.status == "denied"
    assert len(gateway.trace) == 2


def test_gateway_tool_output_is_deterministic() -> None:
    policy = ToolPolicy(
        policy_version="test",
        mode="researcher",
        allowed_tools=frozenset({"rdkit.describe_molecule"}),
    )
    first = ToolGateway(policy, _packet())
    second = ToolGateway(policy, _packet())
    register_read_only_tools(first)
    register_read_only_tools(second)
    request = ToolRequest(
        request_id="r1",
        tool="rdkit.describe_molecule",
        arguments={"canonical_smiles": "CCO"},
        reason="describe",
    )
    assert first.call(request).result == second.call(request).result
