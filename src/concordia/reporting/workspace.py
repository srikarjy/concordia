"""Build an inspectable saved workspace from executed software demonstrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from concordia.colonies.scheduler import ColonyScheduler
from concordia.colonies.schema import ColonySpec
from concordia.genomes import create_seed_genome
from concordia.genomes.schema import EvidenceFamily
from concordia.genomics.evo2 import RecordedFixtureScorer
from concordia.genomics.ism import scan_position
from concordia.genomics.schema import GenomicSequence
from concordia.scientist.genomic_prompt import GENOMIC_SYSTEM_PROMPT
from concordia.verification.cross import (
    ClaimRequest,
    EvidenceRecord,
    ProvenanceArtifact,
    Scope,
    verify_claim,
)
from concordia.verification.measurements import measure_stability


def build_workspace(root: str | Path) -> dict[str, Any]:
    scheduler = ColonyScheduler.local(root)
    store = scheduler.artifacts
    objects: dict[str, Any] = {}

    def save(value: Any) -> str:
        digest = store.put_json(value)
        objects[digest] = value
        return digest

    def envelope(kind: str, payload: Any, parents: tuple[str, ...] = ()) -> str:
        return save(
            ProvenanceArtifact(
                kind=kind,
                payload_digest=save(payload),
                dependencies=parents,
                execution_mode="fixture",
                scientific_use_allowed=False,
                source="Concordia deterministic demonstration",
                producing_tool="workspace-fixture-v1",
            ).model_dump(mode="json")
        )

    sequence = GenomicSequence(
        sequence_id="fixture:workspace",
        sequence="ACGTTGCAACGTGATCGACTACGATCGTACGTTAGCATCGATCGATGC",
        assembly="synthetic-v1",
        region="fixture:0-48",
        strand="+",
    )
    sequence_id = envelope("sequence", sequence.model_dump(mode="json"))
    scorer = RecordedFixtureScorer()
    model_id = envelope(
        "model", {"checkpoint": scorer.model_id, "target": "software_contract_only"}
    )
    effects = [
        effect.model_dump(mode="json")
        for position in range(len(sequence.sequence))
        for effect in scan_position(sequence, position, scorer)
    ]
    scan_id = envelope(
        "evidence", {"method": "in_silico_mutagenesis", "effects": effects}, (sequence_id, model_id)
    )
    nodes = [
        {"id": sequence_id, "label": "Original sequence", "kind": "sequence", "layer": 0},
        {"id": model_id, "label": "Fixture checkpoint", "kind": "model", "layer": 0},
        {"id": scan_id, "label": "144 counterfactuals", "kind": "counterfactual", "layer": 1},
    ]
    edges = [
        {"source": scan_id, "target": sequence_id, "relation": "used"},
        {"source": scan_id, "target": model_id, "relation": "used"},
    ]
    claims = []
    for index, start in enumerate(range(0, len(sequence.sequence), 12)):
        scope = Scope(
            assembly="synthetic-v1",
            chromosome="fixture",
            start=start,
            end=start + 12,
            strand="+",
            model_checkpoint=scorer.model_id,
            scoring_target="software_contract_only",
            assay="synthetic annotation",
        )
        annotation_id = envelope(
            "annotation",
            {
                "annotation_id": f"fixture-interval-{index}",
                "start": start,
                "end": start + 8,
                "assembly": "synthetic-v1",
                "assay": "synthetic annotation",
                "description": "Synthetic interval to exercise overlap; no biological annotation.",
            },
        )
        overlap_id = envelope(
            "evidence", {"overlap_fraction": 8 / 12}, (sequence_id, annotation_id)
        )
        evidence = (
            EvidenceRecord(
                evidence_id=f"counterfactual-{index}",
                family=EvidenceFamily.COUNTERFACTUAL,
                method="in_silico_mutagenesis",
                independence_group="fixture-scorer",
                artifact_digest=scan_id,
                scope=scope,
                assessment="supports",
                strength=1,
                counterfactual_passed=True,
            ),
            EvidenceRecord(
                evidence_id=f"annotation-{index}",
                family=EvidenceFamily.BIOLOGICAL_ANNOTATION,
                method="regulatory_interval_overlap",
                independence_group="fixture-annotation",
                artifact_digest=overlap_id,
                scope=scope,
                assessment="null",
                strength=8 / 12,
            ),
        )
        claim = ClaimRequest(
            claim_id=f"region-{index + 1}",
            text=f"Does model sensitivity in bases {start}–{start + 12} have independent support?",
            scope=scope,
            source_sequence=sequence_id,
            evidence=evidence,
        )
        claim_digest = envelope("claim", claim.model_dump(mode="json"), (scan_id, overlap_id))
        result = verify_claim(claim, store)
        result_digest = save(result.model_dump(mode="json"))
        regional = [value["delta"] for value in effects if start <= value["position"] < start + 12]
        claims.append(
            {
                "id": claim.claim_id,
                "text": claim.text,
                "start": start,
                "end": start + 12,
                "artifact_digest": claim_digest,
                "verification_digest": result_digest,
                "verification": result.model_dump(mode="json"),
                "scope": scope.model_dump(mode="json"),
                "sensitivity": measure_stability(tuple(regional)).model_dump(mode="json"),
            }
        )
        nodes.extend(
            [
                {
                    "id": annotation_id,
                    "label": f"Synthetic interval {index + 1}",
                    "kind": "annotation",
                    "layer": 0,
                },
                {
                    "id": overlap_id,
                    "label": f"Overlap {index + 1}",
                    "kind": "annotation",
                    "layer": 1,
                },
                {"id": claim_digest, "label": f"Region {index + 1}", "kind": "claim", "layer": 2},
                {"id": result_digest, "label": "UNVERIFIABLE", "kind": "verification", "layer": 3},
            ]
        )
        edges.extend(
            [
                {"source": overlap_id, "target": sequence_id, "relation": "used"},
                {"source": overlap_id, "target": annotation_id, "relation": "used"},
                {"source": claim_digest, "target": scan_id, "relation": "supportedBy"},
                {"source": claim_digest, "target": overlap_id, "relation": "used"},
                {"source": result_digest, "target": claim_digest, "relation": "used"},
            ]
        )
    graph = {"schema_version": 1, "nodes": nodes, "edges": edges}
    graph_digest = save(graph)
    task = save(
        {
            "schema_version": 1,
            "sequence_digest": sequence_id,
            "graph_digest": graph_digest,
            "scientific_use_allowed": False,
            "task": "audit fixture sequence regions",
        }
    )
    prompt_digest = store.put_bytes(GENOMIC_SYSTEM_PROMPT.encode())
    objects[prompt_digest] = {"text": GENOMIC_SYSTEM_PROMPT}
    seed = create_seed_genome(prompt_digest)
    spec = ColonySpec(colony_id="workspace-v1", task_artifact_digest=task)
    scheduler.create(spec, seed, idempotency_key="workspace-v1")
    colony = scheduler.run(spec.colony_id)
    for member in (colony.seed_member, *colony.members):
        for digest in (member.genome_digest, member.mutation_digest, member.output_digest):
            if digest:
                objects[digest] = json.loads(store.get_bytes(digest))
    events = [event.model_dump(mode="json") for event in scheduler.ledger.events(spec.colony_id)]
    snapshot = {
        "schema_version": 1,
        "title": "Genomic attribution audit",
        "run_id": spec.colony_id,
        "execution_mode": "deterministic_colony_fixture",
        "scientific_use_allowed": False,
        "sequence": sequence.model_dump(mode="json"),
        "effects": effects,
        "claims": claims,
        "graph": graph,
        "graph_digest": graph_digest,
        "colony": colony.model_dump(mode="json"),
        "events": events,
        "artifacts": objects,
        "study": {
            "status": "AWAITING_REAL_EVIDENCE",
            "protocol_status": "draft",
            "reason": "Real Evo 2 scores and independently sourced annotations are not available.",
        },
    }
    # Snapshot identity names the exact saved events and artifacts shown in the UI.
    snapshot["snapshot_digest"] = store.put_json(snapshot)
    return snapshot
