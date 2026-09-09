import pytest

from concordia.genomics.evo2 import RecordedFixtureScorer
from concordia.genomics.ism import scan_position
from concordia.genomics.schema import GenomicSequence, SequenceVariant, apply_variant
from concordia.graph.schema import EvidenceGraph, GraphEdge, GraphNode
from concordia.storage.content import ContentAddressedStore
from concordia.verification.backtrack import backtrack_claim


def test_variant_and_fixture_scan_are_validated() -> None:
    sequence = GenomicSequence(sequence_id="s1", sequence="ACGT", strand="+")
    altered = apply_variant(
        sequence, SequenceVariant(position=1, reference="C", alternate="T")
    )
    assert altered.sequence == "ATGT"
    effects = scan_position(sequence, 1, RecordedFixtureScorer())
    assert len(effects) == 3
    assert not any(effect.scientific_use_allowed for effect in effects)
    with pytest.raises(ValueError, match="reference mismatch"):
        apply_variant(
            sequence, SequenceVariant(position=1, reference="A", alternate="T")
        )


def test_backtracking_rejects_fixture_evidence() -> None:
    graph = EvidenceGraph(
        nodes=(
            GraphNode(node_id="claim", node_type="Claim", label="claim"),
            GraphNode(
                node_id="fixture",
                node_type="Artifact",
                label="fixture",
                properties={"scientific_use_allowed": False},
            ),
        ),
        edges=(
            GraphEdge(
                edge_id="support", source="claim", target="fixture", relation="supported_by"
            ),
        ),
    )
    result = backtrack_claim(graph, "claim", "fixture")
    assert result.status == "UNVERIFIABLE"
    assert result.path == ("claim", "fixture")


def test_content_store_deduplicates_and_verifies(tmp_path) -> None:
    store = ContentAddressedStore(tmp_path)
    first = store.put_json({"b": 2, "a": 1})
    second = store.put_json({"a": 1, "b": 2})
    assert first == second
    assert store.get_bytes(first) == b'{"a":1,"b":2}'
