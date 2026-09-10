"""Acceptance cases use artificial artifacts, never scientific findings."""

from pathlib import Path

import pytest

from concordia.genomes.schema import EvidenceFamily as Family
from concordia.storage.content import ContentAddressedStore
from concordia.verification.cross import (
    ClaimRequest,
    EvidenceRecord,
    ProvenanceArtifact,
    Scope,
    verify_claim,
)
from concordia.verification.measurements import measure_stability


def setup_case(tmp_path: Path):
    store = ContentAddressedStore(tmp_path)

    # Simulated ingestion metadata tests the real-mode gate, not biological accuracy.
    def artifact(kind, parents=(), mode="real", eligible=True):
        payload = store.put_json({"test_only": True, "kind": kind, "parents": parents})
        return store.put_json(
            ProvenanceArtifact(
                kind=kind,
                payload_digest=payload,
                dependencies=parents,
                execution_mode=mode,
                scientific_use_allowed=eligible,
                source="software acceptance test",
                producing_tool="test-ingestion-v1",
            ).model_dump(mode="json")
        )

    sequence = artifact("sequence")
    scope = Scope(
        assembly="test",
        chromosome="test",
        start=0,
        end=12,
        strand="+",
        model_checkpoint="test-only",
        scoring_target="score",
        assay="test-assay",
    )
    evidence = tuple(
        EvidenceRecord(
            evidence_id=str(i),
            family=family,
            method=method,
            independence_group=group,
            artifact_digest=artifact("evidence", (sequence,)),
            scope=scope,
            assessment="supports",
            strength=1,
            counterfactual_passed=True if family == Family.COUNTERFACTUAL else None,
        )
        for i, (family, method, group) in enumerate(
            [
                (Family.COUNTERFACTUAL, "in_silico_mutagenesis", "perturbation"),
                (Family.BIOLOGICAL_ANNOTATION, "regulatory_interval_overlap", "assay"),
            ]
        )
    )
    claim = ClaimRequest(
        claim_id="test-only",
        text="software test",
        scope=scope,
        source_sequence=sequence,
        evidence=evidence,
    )
    return store, claim, artifact


def test_two_independent_families_and_counterfactual_are_required(tmp_path):
    store, claim, _ = setup_case(tmp_path)
    assert verify_claim(claim, store).status == "SUPPORTED"
    assert verify_claim(
        claim.model_copy(update={"evidence": claim.evidence[:1]}), store
    ).status == ("PARTIALLY_SUPPORTED")
    same_family = claim.evidence[0].model_copy(update={"evidence_id": "duplicate-method"})
    assert (
        verify_claim(
            claim.model_copy(update={"evidence": (claim.evidence[0], same_family)}), store
        ).status
        != "SUPPORTED"
    )


def test_shared_independence_group_and_failed_counterfactual_block_support(tmp_path):
    store, claim, _ = setup_case(tmp_path)
    shared = claim.evidence[1].model_copy(update={"independence_group": "perturbation"})
    assert (
        verify_claim(
            claim.model_copy(update={"evidence": (claim.evidence[0], shared)}), store
        ).status
        == "PARTIALLY_SUPPORTED"
    )
    failed = claim.evidence[0].model_copy(update={"counterfactual_passed": False})
    assert (
        verify_claim(
            claim.model_copy(update={"evidence": (failed, claim.evidence[1])}), store
        ).status
        != "SUPPORTED"
    )


def test_all_provenance_branches_are_checked_for_fixtures(tmp_path):
    store, claim, artifact = setup_case(tmp_path)
    hidden_fixture = artifact("annotation", mode="fixture", eligible=False)
    root = artifact("evidence", (claim.source_sequence, hidden_fixture))
    altered = claim.evidence[1].model_copy(update={"artifact_digest": root})
    result = verify_claim(
        claim.model_copy(update={"evidence": (claim.evidence[0], altered)}), store
    )
    assert result.status == "UNVERIFIABLE"
    assert hidden_fixture in result.checks[1].artifacts_checked


def test_corruption_missing_source_and_out_of_scope_cannot_pass(tmp_path):
    store, claim, artifact = setup_case(tmp_path)
    outside = claim.evidence[1].model_copy(
        update={"scope": claim.scope.model_copy(update={"assembly": "other"})}
    )
    assert (
        verify_claim(
            claim.model_copy(update={"evidence": (claim.evidence[0], outside)}), store
        ).status
        == "UNVERIFIABLE"
    )
    detached = claim.evidence[1].model_copy(update={"artifact_digest": artifact("annotation")})
    assert (
        verify_claim(
            claim.model_copy(update={"evidence": (claim.evidence[0], detached)}), store
        ).status
        == "UNVERIFIABLE"
    )
    store.path_for(claim.source_sequence).write_bytes(b"corrupt test object")
    assert verify_claim(claim, store).status == "UNVERIFIABLE"


def test_critical_contradiction_and_null_results_are_preserved(tmp_path):
    store, claim, _ = setup_case(tmp_path)
    negative = claim.evidence[1].model_copy(update={"assessment": "contradicts", "critical": True})
    result = verify_claim(
        claim.model_copy(update={"evidence": (claim.evidence[0], negative)}), store
    )
    assert result.status == "CONTRADICTED"
    assert result.contradicting_families == (Family.BIOLOGICAL_ANNOTATION,)
    assert (
        verify_claim(claim.model_copy(update={"evidence": ()}), store).status == "MISSING_EVIDENCE"
    )
    assert measure_stability((0, -1, None, 1)).missing_count == 1
    assert measure_stability((0, -1, None, 1)).mean == 0
    assert measure_stability((None,)).sign_agreement is None
    with pytest.raises(ValueError):
        measure_stability((float("nan"),))


def test_verification_is_deterministic_and_does_not_rewrite_claim(tmp_path):
    store, claim, _ = setup_case(tmp_path)
    before = claim.model_dump_json()
    assert verify_claim(claim, store) == verify_claim(claim, store)
    assert claim.model_dump_json() == before


def test_perturbation_cannot_be_relabelled_attribution(tmp_path):
    _, claim, _ = setup_case(tmp_path)
    value = claim.evidence[0].model_dump(mode="json")
    value["family"] = Family.ATTRIBUTION
    with pytest.raises(ValueError, match="counterfactual"):
        EvidenceRecord.model_validate(value)
