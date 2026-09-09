import json

import numpy as np
import pandas as pd

from concordia.evidence.packets import packet_from_row
from concordia.scientist.schema import ScientistResponse
from concordia.scientist.session import run_bounded_session
from concordia.scientist.tools import ToolGateway, ToolPolicy, register_read_only_tools


def _gateway(max_tool_calls=2):
    packet = packet_from_row(
        pd.Series(
            {
                "molecule_id": "tox21:session",
                "canonical_smiles": "CCO",
                "model_id": "rf-test",
                "assay": "NR-AhR",
                "prediction_probability": 0.75,
                "prediction": 1,
            }
        ),
        np.array([0.2, -0.1]),
    )
    gateway = ToolGateway(
        ToolPolicy(
            policy_version="test",
            mode="evaluation",
            allowed_tools=frozenset({"evidence.packet_summary"}),
            max_tool_calls=max_tool_calls,
        ),
        packet,
    )
    register_read_only_tools(gateway)
    return packet, gateway


def test_session_accepts_tool_then_final_response():
    _, gateway = _gateway()
    response = ScientistResponse(summary="done", claims=[]).model_dump_json()
    turns = iter(
        [
            json.dumps(
                {
                    "kind": "tool_request",
                    "tool_request": {
                        "request_id": "r1",
                        "tool": "evidence.packet_summary",
                        "reason": "inspect",
                    },
                }
            ),
            json.dumps({"kind": "final", "response": json.loads(response)}),
        ]
    )
    result = run_bounded_session(gateway.packet, gateway, [], lambda _: next(turns))
    assert result.status == "completed"
    assert result.response.summary == "done"
    assert len(result.tool_trace) == 1


def test_session_stops_at_policy_limit():
    _, gateway = _gateway(max_tool_calls=1)
    request = json.dumps(
        {
            "kind": "tool_request",
            "tool_request": {
                "request_id": "r1",
                "tool": "evidence.packet_summary",
                "reason": "inspect",
            },
        }
    )
    result = run_bounded_session(gateway.packet, gateway, [], lambda _: request)
    assert result.status == "limit_exceeded"
    assert len(result.tool_trace) == 2
