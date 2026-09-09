"""Backtrack claims through evidence and provenance nodes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from concordia.graph.schema import EvidenceGraph


class BacktrackingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_node_id: str
    target_node_id: str
    status: Literal["SUPPORTED", "UNVERIFIABLE", "MISSING_EVIDENCE"]
    path: tuple[str, ...] = ()
    scientific_use_allowed: bool
    reasons: tuple[str, ...] = ()


def backtrack_claim(
    graph: EvidenceGraph,
    claim_node_id: str,
    target_node_id: str,
) -> BacktrackingResult:
    node_by_id = {node.node_id: node for node in graph.nodes}
    if claim_node_id not in node_by_id or target_node_id not in node_by_id:
        return BacktrackingResult(
            claim_node_id=claim_node_id,
            target_node_id=target_node_id,
            status="MISSING_EVIDENCE",
            scientific_use_allowed=False,
            reasons=("claim or target node is absent",),
        )
    path = graph.path(claim_node_id, target_node_id)
    if path is None:
        return BacktrackingResult(
            claim_node_id=claim_node_id,
            target_node_id=target_node_id,
            status="UNVERIFIABLE",
            scientific_use_allowed=False,
            reasons=("no directed provenance path exists",),
        )
    disallowed = [
        node_id
        for node_id in path
        if node_by_id[node_id].properties.get("scientific_use_allowed") is False
    ]
    if disallowed:
        return BacktrackingResult(
            claim_node_id=claim_node_id,
            target_node_id=target_node_id,
            status="UNVERIFIABLE",
            path=path,
            scientific_use_allowed=False,
            reasons=("path contains software-only fixture evidence",),
        )
    return BacktrackingResult(
        claim_node_id=claim_node_id,
        target_node_id=target_node_id,
        status="SUPPORTED",
        path=path,
        scientific_use_allowed=True,
    )
