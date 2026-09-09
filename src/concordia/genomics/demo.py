"""Zero-cost genomic vertical slice using explicitly non-scientific fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from concordia.artifacts import write_json
from concordia.genomics.evo2 import RecordedFixtureScorer
from concordia.genomics.ism import scan_position
from concordia.genomics.schema import GenomicSequence
from concordia.graph.schema import EvidenceGraph, GraphEdge, GraphNode
from concordia.storage.content import ContentAddressedStore
from concordia.verification.backtrack import backtrack_claim


def run_genomic_fixture_demo(output_directory: str | Path) -> dict[str, Any]:
    """Exercise the graph contract without representing results as Evo2 evidence."""
    output = Path(output_directory)
    store = ContentAddressedStore(output / "objects")
    sequence = GenomicSequence(
        sequence_id="fixture:regulatory-region-1",
        sequence="ACGTTGCAACGT",
        assembly=None,
        region=None,
        strand="+",
    )
    scorer = RecordedFixtureScorer()
    score = scorer.score(sequence)
    effects = scan_position(sequence, position=4, scorer=scorer)
    strongest = max(effects, key=lambda effect: abs(effect.delta))
    sequence_artifact = store.put_json(sequence.model_dump(mode="json"))
    score_artifact = store.put_json(score.model_dump(mode="json"))
    effect_artifact = store.put_json(strongest.model_dump(mode="json"))
    graph = EvidenceGraph(
        nodes=(
            GraphNode(
                node_id="claim:fixture-1",
                node_type="ScientificClaim",
                label="Fixture score changes after one substitution",
                properties={"scientific_use_allowed": False},
            ),
            GraphNode(
                node_id=f"effect:{effect_artifact}",
                node_type="CounterfactualEffect",
                label=f"Position {strongest.position} {strongest.reference}>{strongest.alternate}",
                properties={"scientific_use_allowed": False, "artifact_hash": effect_artifact},
            ),
            GraphNode(
                node_id=f"score:{score_artifact}",
                node_type="ModelOutput",
                label=scorer.model_id,
                properties={"scientific_use_allowed": False, "artifact_hash": score_artifact},
            ),
            GraphNode(
                node_id=f"sequence:{sequence_artifact}",
                node_type="GenomicSequence",
                label=sequence.sequence_id,
                properties={"scientific_use_allowed": False, "artifact_hash": sequence_artifact},
            ),
        ),
        edges=(
            GraphEdge(
                edge_id="edge:claim-effect",
                source="claim:fixture-1",
                target=f"effect:{effect_artifact}",
                relation="supported_by",
            ),
            GraphEdge(
                edge_id="edge:effect-score",
                source=f"effect:{effect_artifact}",
                target=f"score:{score_artifact}",
                relation="derived_from",
            ),
            GraphEdge(
                edge_id="edge:score-sequence",
                source=f"score:{score_artifact}",
                target=f"sequence:{sequence_artifact}",
                relation="used",
            ),
        ),
    )
    verification = backtrack_claim(
        graph, "claim:fixture-1", f"sequence:{sequence_artifact}"
    )
    graph_artifact = store.put_json(graph.model_dump(mode="json"))
    result = {
        "mode": "recorded_fixture",
        "scientific_use_allowed": False,
        "warning": "Software demonstration only; this is not an Evo2 result.",
        "graph_artifact": graph_artifact,
        "verification": verification.model_dump(mode="json"),
    }
    write_json(output / "manifest.json", result)
    return result
