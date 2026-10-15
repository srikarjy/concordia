"""Structure-claim rules use artificial measurements, never scientific findings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from concordia.genomes.schema import EvidenceFamily as Family
from concordia.storage.content import ContentAddressedStore
from concordia.verification.cross import (
    ClaimRequest,
    EvidenceRecord,
    ProvenanceArtifact,
    Scope,
    StructureScope,
    verify_claim,
)
from concordia.verification.structure_rules import (
    StructureMeasurements,
    agreement,
    counterfactual,
    evidence_records,
    plausibility,
)

DIGEST = "0" * 64
SCOPE = StructureScope(
    complex_id="test-complex",
    receptor_chains=("H", "L"),
    ligand_chains=("A",),
    model_checkpoint="test-only",
    settings_digest=DIGEST,
    assay="predicted_interface",
)
CLEAN = StructureMeasurements(clash_count=0, variable_domain_fraction=1.0, buried_surface_area=1700)


def test_structure_scope_rejects_shared_chains():
    with pytest.raises(ValidationError):
        StructureScope(**{**SCOPE.model_dump(), "ligand_chains": ("H",)})


def test_genomic_scope_serialization_is_unchanged():
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
    assert "kind" not in scope.model_dump()
    record = EvidenceRecord(
        evidence_id="1",
        family=Family.LITERATURE,
        method="m",
        independence_group="g",
        artifact_digest=DIGEST,
        scope=scope,
        assessment="null",
        strength=0,
    )
    assert isinstance(EvidenceRecord.model_validate_json(record.model_dump_json()).scope, Scope)


def test_structure_families_require_structure_scope():
    genomic = Scope(
        assembly="test",
        chromosome="test",
        start=0,
        end=12,
        strand="+",
        model_checkpoint="test-only",
        scoring_target="score",
        assay="test-assay",
    )
    with pytest.raises(ValidationError, match="requires a structure scope"):
        EvidenceRecord(
            evidence_id="1",
            family=Family.PHYSICAL_PLAUSIBILITY,
            method="m",
            independence_group="g",
            artifact_digest=DIGEST,
            scope=genomic,
            assessment="supports",
            strength=1,
        )


def test_plausibility_rules():
    assert plausibility(CLEAN) == ("supports", ())
    assert plausibility(StructureMeasurements())[0] == "missing"
    status, reasons = plausibility(CLEAN.model_copy(update={"clash_count": 16}))
    assert status == "contradicts" and "16 interface clashes" in reasons
    assert plausibility(CLEAN.model_copy(update={"variable_domain_fraction": 0.7}))[0] == (
        "contradicts"
    )
    assert plausibility(CLEAN.model_copy(update={"buried_surface_area": 300}))[0] == "contradicts"


def test_agreement_and_counterfactual_thresholds():
    assert [agreement(v) for v in (None, 0.6, 0.3, 0.1)] == [
        "missing",
        "supports",
        "null",
        "contradicts",
    ]
    assert counterfactual(None) is None
    assert counterfactual(0.05) is True  # the interface moved when the paratope changed
    assert counterfactual(0.8) is False


def test_reference_is_excluded_unless_requested():
    measured = CLEAN.model_copy(update={"reference_dockq": 0.1})
    artifacts = {"physical": DIGEST, "reference": DIGEST}
    names = [r.evidence_id for r in evidence_records(measured, SCOPE, artifacts)]
    assert names == ["test-complex:physical"]
    with_reference = evidence_records(measured, SCOPE, artifacts, include_reference=True)
    assert with_reference[-1].family == Family.STRUCTURAL_REFERENCE
    assert with_reference[-1].critical


def _claim(tmp_path: Path, measured: StructureMeasurements):
    store = ContentAddressedStore(tmp_path)

    def envelope(kind, parents=()):
        payload = store.put_json({"test_only": True, "kind": kind})
        return store.put_json(
            ProvenanceArtifact(
                kind=kind,
                payload_digest=payload,
                dependencies=parents,
                execution_mode="real",
                scientific_use_allowed=True,
                source="software acceptance test",
                producing_tool="test-structure-v1",
            ).model_dump(mode="json")
        )

    source = envelope("sequence")
    names = ("physical", "samples", "second_model", "counterfactual", "reference")
    artifacts = {name: envelope("evidence", (source,)) for name in names}
    claim = ClaimRequest(
        claim_id="test-complex",
        text="software test",
        scope=SCOPE,
        source_sequence=source,
        evidence=evidence_records(measured, SCOPE, artifacts),
    )
    return verify_claim(claim, store)


def test_independent_agreement_and_counterfactual_support_a_pose(tmp_path):
    measured = CLEAN.model_copy(
        update={
            "second_model_interface_agreement": 0.7,
            "perturbed_paratope_interface_agreement": 0.0,
        }
    )
    assert _claim(tmp_path, measured).status == "SUPPORTED"


def test_physical_plausibility_alone_cannot_carry_a_claim(tmp_path):
    result = _claim(tmp_path, CLEAN)
    assert result.status == "MISSING_EVIDENCE"
    assert "insufficient independent supporting evidence families" in result.reasons


def test_implausible_pose_is_contradicted(tmp_path):
    assert _claim(tmp_path, CLEAN.model_copy(update={"clash_count": 16})).status == "CONTRADICTED"


def test_same_model_samples_do_not_count_as_independent_support(tmp_path):
    measured = CLEAN.model_copy(
        update={"sample_interface_agreement": 0.9, "perturbed_paratope_interface_agreement": 0.0}
    )
    result = _claim(tmp_path, measured)
    assert result.status == "PARTIALLY_SUPPORTED"
    assert "insufficient independent supporting evidence families" in result.reasons


def test_second_model_disagreement_contradicts_a_plausible_pose(tmp_path):
    measured = CLEAN.model_copy(update={"second_model_interface_agreement": 0.05})
    assert _claim(tmp_path, measured).status == "CONTRADICTED"
