from datetime import timedelta
from pathlib import Path

import pytest

from concordia.campaigns.artifacts import CampaignArtifactStore, ObjectStorageArtifactStore
from concordia.campaigns.assay import parse_assay_csv
from concordia.campaigns.benchmark import run_retrospective_benchmark
from concordia.campaigns.connectors import (
    BioNeMoInferenceConnector,
    BioNeMoTrainingConnector,
    BoltzCampaignConnector,
    HttpBioNeMoInferenceRunner,
    HttpBioNeMoTrainingRunner,
    ProteinBaselineTrainingConnector,
    UnconfiguredBioNeMoInferenceRunner,
    UnconfiguredBioNeMoTrainingRunner,
)
from concordia.campaigns.design import (
    DesignEvaluation,
    build_binder_design_plan,
    rank_designs,
    stage_requests,
)
from concordia.campaigns.policy import (
    RetentionPolicy,
    export_candidates,
    retention_decision,
)
from concordia.campaigns.postgres import CAMPAIGN_SCHEMA_STATEMENTS
from concordia.campaigns.recommendations import SelectionCandidate, select_candidates
from concordia.campaigns.redaction import redact_for_log
from concordia.campaigns.replay import replay_execute, replay_read
from concordia.campaigns.reporting import build_report_manifest, verify_report_manifest
from concordia.campaigns.schema import AssayStatus, ModelRunStatus
from concordia.campaigns.security import (
    CampaignAction,
    CampaignPrincipal,
    OrganizationRole,
    require_action,
    rotate_secret,
    verify_secret,
)
from concordia.campaigns.service import (
    AddCandidateRequest,
    CampaignConflictError,
    CampaignStore,
    CreateCampaignRequest,
    CreateEvidenceClaimRequest,
    CreateRoundRequest,
    CreateStudyRequest,
    EnqueueModelJobRequest,
    ModelJobStatus,
    RecordMeasurementRequest,
    RecordModelRunRequest,
)
from concordia.campaigns.training import (
    ProteinTrainingExample,
    freeze_protein_dataset,
    train_protein_baseline,
)
from concordia.campaigns.validation import (
    validate_campaign_round,
    validate_measurement_semantics,
    validate_model_run_lineage,
    validate_recommendation_replay,
)
from concordia.campaigns.worker import (
    CampaignModelWorker,
    ConnectorResult,
    ModelExecutionContext,
)
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzResult


def test_unconfigured_bionemo_adapters_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="adapter present, no endpoint configured"):
        UnconfiguredBioNeMoTrainingRunner().train(
            dataset_id="dataset", model="model", framework_version="v1", parameters={}
        )
    with pytest.raises(RuntimeError, match="adapter present, no endpoint configured"):
        UnconfiguredBioNeMoInferenceRunner().infer(
            model="model", sequences=("ACDE",), parameters={}
        )


def test_assay_csv_preserves_censored_and_failed_statuses() -> None:
    report = parse_assay_csv(
        "candidate_id,metric,value,unit,method,status,replicate\n"
        "c-1,binding,0.2,nM,BLI,measured,1\n"
        "c-2,binding,0.5,nM,BLI,below_detection,1\n"
        "c-3,binding,,nM,BLI,failed_expression,1\n"
    )
    assert report.valid
    assert report.accepted_count == 3
    assert report.rows[1].status is AssayStatus.BELOW_DETECTION
    assert report.rows[2].status is AssayStatus.FAILED_EXPRESSION
    assert report.rows[2].value is None


def test_typed_measurement_contract_rejects_missing_numeric_censored_value() -> None:
    with pytest.raises(ValueError, match="value is required"):
        RecordMeasurementRequest(
            candidate_id="candidate-1",
            metric="binding",
            value=None,
            unit="nM",
            method="BLI",
            status=AssayStatus.MEASURED,
        )


def test_campaign_validation_gate_requires_inputs_and_preserves_scientific_boundary() -> None:
    empty = validate_campaign_round((), ())
    assert not empty.passed
    assert empty.scientific_use_allowed is False
    assert empty.prospective_claim_allowed is False

    from concordia.campaigns.schema import CampaignAuditEvent, DatasetSnapshot, utc_now

    dataset = DatasetSnapshot(
        dataset_id="dataset-1",
        campaign_id="campaign-1",
        round_id="round-1",
        measurement_ids=(),
        transformation_policy="measured_only",
        dataset_digest="a" * 64,
        row_count=0,
        created_at=utc_now(),
    )
    without_benchmark = validate_campaign_round((), (), (dataset,), ())
    assert not without_benchmark.passed
    benchmark_without_artifact = CampaignAuditEvent(
        event_id="event-missing-artifact",
        campaign_id="campaign-1",
        actor="owner",
        action="benchmark.completed",
        resource_type="dataset",
        resource_id="dataset-1",
        payload={"benchmark_digest": "b" * 64},
        created_at=utc_now(),
    )
    assert not validate_campaign_round(
        (), (), (dataset,), (benchmark_without_artifact,)
    ).passed
    benchmark_event = CampaignAuditEvent(
        event_id="event-1",
        campaign_id="campaign-1",
        actor="owner",
        action="benchmark.completed",
        resource_type="dataset",
        resource_id="dataset-1",
        payload={"benchmark_digest": "b" * 64, "artifact_digest": "c" * 64},
        created_at=utc_now(),
    )
    with_benchmark = validate_campaign_round((), (), (dataset,), (benchmark_event,))
    assert with_benchmark.passed


def test_campaign_study_freeze_and_admission_fail_closed(tmp_path: Path) -> None:
    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="study", objective="binder", target_sequence="MKT"
        )
    )
    round_record = store.create_round(
        campaign.campaign_id, CreateRoundRequest(protocol_version="v1")
    )
    candidate = store.add_candidate(
        round_record.round_id, AddCandidateRequest(sequence="ACDE", source="assay")
    )
    store.record_measurement(
        round_record.round_id,
        RecordMeasurementRequest(
            candidate_id=candidate.candidate_id,
            metric="binding",
            value=1.0,
            unit="nM",
            method="fixture",
            status=AssayStatus.MEASURED,
        ),
    )
    dataset = store.freeze_dataset(round_record.round_id, "measured_only")
    study = store.create_study(
        round_record.round_id,
        CreateStudyRequest(
            protocol_digest="a" * 64,
            dataset_digest=dataset.dataset_digest,
            selection_manifest_digest="b" * 64,
            model_pin="baseline@1",
            evidence_families=("assay", "structure"),
            preregistered_outcomes=("binding",),
        ),
    )
    store.freeze_study_record(study.study_id)
    admitted, admitted_report = store.admit_study(study.study_id)
    assert admitted.status.value == "blocked"
    assert not admitted_report.passed
    assert (
        "a retrospective benchmark must be recorded before admission" in admitted.admission_reasons
    )


def test_model_replay_modes_never_confuse_rerun_with_exact_replay() -> None:
    from concordia.campaigns.schema import CampaignModelRun, ModelRunStatus, utc_now

    source = CampaignModelRun(
        model_run_id="source-run",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=(),
        provider="concordia-protein-baseline",
        model="baseline",
        model_version="1",
        execution_mode="local_training",
        parameters={},
        input_artifact_digests=(),
        output_artifact_digests=("a" * 64,),
        status=ModelRunStatus.COMPLETED,
        scientific_use_allowed=False,
        created_at=utc_now(),
        input_digest="b" * 64,
        parameter_digest="c" * 64,
    )
    recorded = replay_read(source)
    assert recorded.exact is True
    rerun = source.model_copy(
        update={
            "model_run_id": "rerun",
            "status": ModelRunStatus.QUEUED,
            "output_artifact_digests": (),
        }
    )
    executed = replay_execute(source, rerun)
    assert executed.exact is False
    assert executed.drift_detected is None


def test_campaign_artifacts_are_typed_and_integrity_checked(tmp_path: Path) -> None:
    from concordia.storage.content import ContentAddressedStore

    artifacts = CampaignArtifactStore(ContentAddressedStore(tmp_path / "artifacts"))
    reference = artifacts.put(b"pdb-bytes", kind="structure", media_type="chemical/x-pdb")
    assert reference.storage_key.startswith("campaign-artifacts/structure/")
    assert artifacts.get(reference) == b"pdb-bytes"


def test_object_storage_artifacts_use_content_addressed_keys() -> None:
    class FakeObjectStore:
        def __init__(self):
            self.objects = {}

        def put_object(self, *, bucket, key, body, content_type):
            self.objects[(bucket, key)] = (body, content_type)

        def get_object(self, *, bucket, key):
            return self.objects[(bucket, key)][0]

    store = FakeObjectStore()
    artifacts = ObjectStorageArtifactStore(store, bucket="bio-artifacts")
    reference = artifacts.put(
        b"checkpoint", kind="checkpoint", media_type="application/octet-stream"
    )
    assert reference.storage_key.startswith("concordia/campaign-artifacts/checkpoint/sha256/")
    assert artifacts.get(reference) == b"checkpoint"


def test_retrospective_benchmark_is_repeated_seed_and_non_scientific() -> None:
    examples = tuple(
        ProteinTrainingExample(f"c-{index}", sequence, float(index))
        for index, sequence in enumerate(("AAAA", "AAAT", "AATT", "ATTT", "TTTT", "GGGG"))
    )
    benchmark = run_retrospective_benchmark(examples, seeds=(1, 2))
    assert len(benchmark.runs) == 2
    assert all(run.predictor_metrics["n"] >= 1 for run in benchmark.runs)
    assert benchmark.prospective_claim_allowed is False
    assert benchmark.scientific_use_allowed is False


def test_binder_design_plan_composes_allowlisted_stages_and_ranks_controls() -> None:
    plan = build_binder_design_plan(
        plan_id="plan-1",
        target_structure_digest="a" * 64,
        contigs="A1-100/0 15-25",
        hotspot_residues=("A50",),
        num_backbones=2,
        sequences_per_backbone=2,
        max_cofolds=2,
        budget_units=4,
    )
    assert [request.provider for request in stage_requests(plan)] == [
        "nvidia-rfdiffusion",
        "nvidia-proteinmpnn",
        "nvidia-boltz",
    ]
    evaluations = (
        DesignEvaluation(
            design_id="pass",
            backbone_artifact_digest="b" * 64,
            sequence_artifact_digest="c" * 64,
            complex_artifact_digest="d" * 64,
            iptm=0.9,
            binder_plddt=90,
            self_consistency_rmsd=1.0,
        ),
        DesignEvaluation(
            design_id="fail",
            backbone_artifact_digest="e" * 64,
            sequence_artifact_digest="f" * 64,
            complex_artifact_digest="0" * 64,
            iptm=0.5,
            binder_plddt=60,
            self_consistency_rmsd=4.0,
        ),
    )
    ranking = rank_designs(plan, evaluations)
    assert ranking.passing_design_ids == ("pass",)
    assert ranking.success_rate == 0.5
    assert ranking.scientific_use_allowed is False


def test_roles_and_rotating_secrets_fail_closed() -> None:
    principal = CampaignPrincipal("user-1", "org-a", OrganizationRole.VIEWER)
    require_action(principal, CampaignAction.READ)
    with pytest.raises(PermissionError):
        require_action(principal, CampaignAction.RUN_MODEL)
    raw_secret, record = rotate_secret("nvidia", lifetime=timedelta(hours=1))
    assert verify_secret(record, raw_secret)
    assert not verify_secret(record, "wrong")
    assert raw_secret not in record.digest


def test_exports_redact_sequences_and_retention_respects_legal_hold() -> None:
    from datetime import UTC, datetime, timedelta

    from concordia.campaigns.schema import Candidate, utc_now

    candidate = Candidate(
        candidate_id="candidate-1",
        campaign_id="campaign-1",
        round_id="round-1",
        sequence="ACDE",
        sequence_hash="a" * 64,
        parent_ids=(),
        source="import",
        construct_metadata={},
        created_at=utc_now(),
    )
    principal = CampaignPrincipal("user-1", "org-a", OrganizationRole.VIEWER)
    exported = export_candidates((candidate,), principal)
    assert "sequence" not in exported[0]
    with pytest.raises(PermissionError):
        export_candidates((candidate,), principal, include_raw_sequences=True, purpose="audit")
    decision = retention_decision(
        datetime.now(UTC) - timedelta(days=400),
        kind="artifact",
        policy=RetentionPolicy(legal_hold=True),
    )
    assert decision.eligible is False


def test_log_redaction_never_returns_raw_sequences_or_credentials() -> None:
    payload = redact_for_log(
        {"sequence": "ACDE", "access_token": "token-value", "nested": {"secret": "key"}}
    )
    serialized = str(payload)
    assert "ACDE" not in serialized
    assert "token-value" not in serialized
    assert "key" not in serialized
    assert payload["sequence"]["redacted"] is True


def test_postgres_campaign_store_contract_migrates_and_scopes_tokens(monkeypatch) -> None:
    import psycopg

    from concordia.campaigns.postgres import (
        CAMPAIGN_SCHEMA_STATEMENTS,
        CAMPAIGN_SCHEMA_VERSION,
        PostgresCampaignStore,
    )

    class Cursor:
        def __init__(self, state):
            self.state = state
            self.calls = []
            self.result = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            self.calls.append((query, params))
            if "INSERT INTO concordia_campaigns" in query:
                self.state["campaign"] = {
                    "campaign_id": params[0],
                    "campaign_json": params[2],
                    "access_token_hash": params[3],
                }
            elif "SELECT campaign_json" in query:
                self.result = {"campaign_json": self.state["campaign"]["campaign_json"]}
            elif "SELECT access_token_hash" in query:
                self.result = {"access_token_hash": self.state["campaign"]["access_token_hash"]}

        def fetchone(self):
            result, self.result = self.result, None
            return result

        def fetchall(self):
            return []

    class Connection:
        def __init__(self):
            self.state = {}
            self.cursors = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            cursor = Cursor(self.state)
            self.cursors.append(cursor)
            return cursor

        def commit(self):
            return None

    connection = Connection()
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: connection)
    store = PostgresCampaignStore("postgresql://test")
    created = store.create_campaign_with_token(
        CreateCampaignRequest(
            organization_id="org-a", title="postgres", objective="test", target_sequence="MKT"
        )
    )
    assert created.access_token
    assert len(connection.cursors[0].calls) == len(CAMPAIGN_SCHEMA_STATEMENTS) + 1
    migration_calls = [
        call for call in connection.cursors[0].calls if "schema_migrations" in call[0]
    ]
    assert migration_calls[-1][1] == (CAMPAIGN_SCHEMA_VERSION,)
    assert connection.state["campaign"]["access_token_hash"] != created.access_token
    assert (
        store.get_campaign(created.campaign.campaign_id).campaign_id == created.campaign.campaign_id
    )
    store.authorize(created.campaign.campaign_id, created.access_token)
    with pytest.raises(CampaignConflictError):
        store.authorize(created.campaign.campaign_id, "wrong")


def test_assay_csv_rejects_duplicates_and_invalid_measurement_values() -> None:
    report = parse_assay_csv(
        "candidate_id,metric,value,unit,method,status,replicate\n"
        "c-1,binding,not-a-number,nM,BLI,measured,1\n"
        "c-1,binding,0.2,nM,BLI,measured,1\n"
    )
    assert not report.valid
    assert any("finite number" in error.message for error in report.errors)
    assert any("duplicate" in error.message for error in report.errors)


def test_selection_policies_are_deterministic_and_fail_closed_on_missing_scores() -> None:
    candidates = (
        SelectionCandidate("a", score=0.2, sequence="AAAA"),
        SelectionCandidate("b", score=0.9, sequence="AAAT"),
        SelectionCandidate("c", score=0.4, sequence="TTTT"),
    )
    assert select_candidates(candidates, policy="greedy", batch_size=2).candidate_ids == (
        "b",
        "c",
    )
    first = select_candidates(candidates, policy="diversity", batch_size=2, seed=7)
    second = select_candidates(candidates, policy="diversity", batch_size=2, seed=7)
    assert first == second
    with pytest.raises(ValueError, match="requires a score"):
        select_candidates(
            (SelectionCandidate("a", sequence="AAAA"),), policy="greedy", batch_size=1
        )


def test_protein_baseline_is_replayable_and_not_scientific_validation() -> None:
    examples = tuple(
        ProteinTrainingExample(candidate_id=f"c-{index}", sequence=sequence, value=float(index))
        for index, sequence in enumerate(("AAAA", "AAAT", "AATT", "TTTT", "GGGG"))
    )
    first_dataset = freeze_protein_dataset("dataset-1", examples, seed=4)
    second_dataset = freeze_protein_dataset("dataset-1", examples, seed=4)
    assert first_dataset.dataset_digest == second_dataset.dataset_digest
    first = train_protein_baseline(first_dataset)
    second = train_protein_baseline(second_dataset)
    assert first.artifact_digest == second.artifact_digest
    assert first.metrics["test"]["n"] >= 1
    assert first.scientific_use_allowed is False


def test_protein_baseline_connector_returns_a_job_artifact(tmp_path: Path) -> None:
    from concordia.storage.content import ContentAddressedStore

    class Provider:
        def get_training_examples(self, dataset_id: str, *, metric: str | None = None):
            assert dataset_id == "dataset-1"
            assert metric == "binding"
            return (
                ProteinTrainingExample("c-1", "AAAA", 0.1),
                ProteinTrainingExample("c-2", "TTTT", 0.9),
                ProteinTrainingExample("c-3", "GGGG", 0.5),
            )

    from concordia.campaigns.schema import CampaignModelRun, ModelRunStatus, utc_now

    run = CampaignModelRun(
        model_run_id="run-baseline",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=(),
        provider="concordia-protein-baseline",
        model="protein_composition_ridge_v1",
        model_version="1",
        execution_mode="local_training",
        parameters={"dataset_id": "dataset-1", "metric": "binding"},
        input_artifact_digests=(),
        output_artifact_digests=(),
        status=ModelRunStatus.QUEUED,
        scientific_use_allowed=False,
        created_at=utc_now(),
    )
    result = ProteinBaselineTrainingConnector(
        Provider(), CampaignArtifactStore(ContentAddressedStore(tmp_path / "artifacts"))
    ).execute(ModelExecutionContext(model_run=run, candidates=()))
    assert result.provider_request_id.startswith("concordia-baseline:")
    assert len(result.output_artifact_digests) == 1


def test_release_validation_gates_lineage_and_recommendation_replay() -> None:
    from concordia.campaigns.schema import (
        CampaignModelRun,
        Measurement,
        ModelRunStatus,
        Recommendation,
        utc_now,
    )

    run = CampaignModelRun(
        model_run_id="run-validate",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=(),
        provider="concordia-protein-baseline",
        model="baseline",
        model_version="1",
        execution_mode="local_training",
        parameters={},
        input_artifact_digests=(),
        output_artifact_digests=("artifact-1",),
        status=ModelRunStatus.COMPLETED,
        scientific_use_allowed=False,
        created_at=utc_now(),
        input_digest="a" * 64,
        parameter_digest="b" * 64,
    )
    assert validate_model_run_lineage(run).passed
    measurement = Measurement(
        measurement_id="measurement-1",
        round_id="round-1",
        candidate_id="candidate-1",
        metric="binding",
        value=None,
        unit="nM",
        method="BLI",
        status="failed_expression",
        replicate=1,
        source_artifact_digest=None,
        created_at=utc_now(),
    )
    assert validate_measurement_semantics((measurement,)).passed
    selection = select_candidates(
        (SelectionCandidate("a", score=0.1), SelectionCandidate("b", score=0.9)),
        policy="greedy",
        batch_size=1,
    )
    recommendation = Recommendation(
        recommendation_id="rec-1",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=selection.candidate_ids,
        policy="greedy",
        evidence_snapshot=(),
        rationale={},
        status="draft",
        created_at=utc_now(),
    )
    assert validate_recommendation_replay(
        recommendation,
        (SelectionCandidate("a", score=0.1), SelectionCandidate("b", score=0.9)),
        batch_size=1,
        seed=0,
    ).passed


def test_postgres_campaign_schema_preserves_security_and_lineage_contract() -> None:
    schema = "\n".join(CAMPAIGN_SCHEMA_STATEMENTS)
    assert "access_token_hash TEXT NOT NULL" in schema
    assert "REFERENCES concordia_campaigns(campaign_id)" in schema
    assert "REFERENCES concordia_candidates(candidate_id)" in schema
    assert "dataset_digest TEXT NOT NULL" in schema
    assert "lease_expires_at TIMESTAMPTZ" in schema
    assert "concordia_evidence_claims" in schema
    assert "concordia_campaign_audit_events" in schema


def test_evidence_claims_fail_closed_until_independently_validated(tmp_path: Path) -> None:
    from concordia.campaigns.schema import EvidenceStatus

    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="evidence", objective="test", target_sequence="MKT"
        )
    )
    round_record = store.create_round(
        campaign.campaign_id, CreateRoundRequest(protocol_version="v1")
    )
    claim = store.create_evidence_claim(
        round_record.round_id,
        CreateEvidenceClaimRequest(
            subject_id="candidate-1",
            claim_type="binding",
            statement="Candidate may bind the target.",
        ),
    )
    with pytest.raises(CampaignConflictError, match="independent validation"):
        store.verify_evidence_claim(
            claim.claim_id,
            status=EvidenceStatus.SUPPORTED,
            verifier="reviewer",
        )
    rejected = store.verify_evidence_claim(
        claim.claim_id,
        status=EvidenceStatus.REJECTED,
        verifier="reviewer",
    )
    assert rejected.scientific_use_allowed is False


def test_campaign_and_round_lifecycle_rejects_invalid_transitions(tmp_path: Path) -> None:
    from concordia.campaigns.schema import CampaignStatus, RoundStatus

    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="lifecycle", objective="test", target_sequence="MKT"
        )
    )
    round_record = store.create_round(
        campaign.campaign_id, CreateRoundRequest(protocol_version="v1")
    )
    active_campaign = store.transition_campaign(campaign.campaign_id, CampaignStatus.ACTIVE)
    assert active_campaign.status is CampaignStatus.ACTIVE
    with pytest.raises(CampaignConflictError, match="cannot transition"):
        store.transition_campaign(campaign.campaign_id, CampaignStatus.DRAFT)
    active_round = store.transition_round(round_record.round_id, RoundStatus.ACTIVE)
    assert active_round.status is RoundStatus.ACTIVE
    complete_round = store.transition_round(round_record.round_id, RoundStatus.RESULTS_COMPLETE)
    assert complete_round.status is RoundStatus.RESULTS_COMPLETE
    with pytest.raises(CampaignConflictError, match="cannot transition"):
        store.transition_round(round_record.round_id, RoundStatus.ACTIVE)
    with pytest.raises(CampaignConflictError, match="read-only"):
        store.add_candidate(
            round_record.round_id,
            AddCandidateRequest(sequence="ACDE", source="late-write"),
        )
    closed_campaign = store.transition_campaign(campaign.campaign_id, CampaignStatus.CLOSED)
    assert closed_campaign.status is CampaignStatus.CLOSED
    with pytest.raises(CampaignConflictError, match="read-only"):
        store.create_round(campaign.campaign_id, CreateRoundRequest(protocol_version="v2"))
    event = store.append_audit_event(
        campaign.campaign_id,
        actor="reviewer",
        action="test.sequence.logged",
        resource_type="candidate",
        resource_id="candidate-1",
        payload={"sequence": "ACDE"},
    )
    events = store.list_audit_events(campaign.campaign_id)
    assert event in events
    assert "ACDE" not in event.model_dump_json()
    assert any(item.action == "campaign.status.transitioned" for item in events)


def test_report_manifest_redacts_sequences_and_is_content_addressed() -> None:
    from concordia.campaigns.schema import Campaign, CampaignStatus, utc_now

    campaign = Campaign(
        campaign_id="campaign-1",
        organization_id="org-a",
        title="report",
        objective="test",
        target_sequence="MKT",
        target_construct={},
        status=CampaignStatus.DRAFT,
        created_at=utc_now(),
    )
    manifest = build_report_manifest(campaign, generated_at=utc_now())
    serialized = str(manifest)
    assert "MKT" not in serialized
    assert manifest["format"] == "concordia-biorender-manifest-v1"
    assert manifest["figures"][0]["biorender_editable"] is True
    assert manifest["scientific_use_allowed"] is False
    assert len(manifest["manifest_digest"]) == 64
    assert verify_report_manifest(manifest)
    tampered = {**manifest, "scientific_use_allowed": True}
    assert not verify_report_manifest(tampered)


def test_campaign_round_lineage_measurements_and_frozen_dataset(tmp_path: Path) -> None:
    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a",
            title="binder campaign",
            objective="find soluble research binders",
            target_sequence="MKT",
        )
    )
    round_record = store.create_round(
        campaign.campaign_id,
        CreateRoundRequest(protocol_version="assay-v1", batch_size=2),
    )
    parent = store.add_candidate(
        round_record.round_id,
        AddCandidateRequest(sequence="ACDE", source="import"),
    )
    child = store.add_candidate(
        round_record.round_id,
        AddCandidateRequest(sequence="ACDF", source="mutation", parent_ids=(parent.candidate_id,)),
    )
    measurement = store.record_measurement(
        round_record.round_id,
        RecordMeasurementRequest(
            candidate_id=child.candidate_id,
            metric="binding_signal",
            value=0.42,
            unit="RU",
            method="BLI",
            status=AssayStatus.MEASURED,
        ),
    )
    dataset = store.freeze_dataset(
        round_record.round_id, "exclude_invalid; preserve_censored_values"
    )

    assert child.parent_ids == (parent.candidate_id,)
    assert dataset.measurement_ids == (measurement.measurement_id,)
    assert dataset.transformation_policy.startswith("exclude_invalid")

    model_run = store.record_model_run(
        round_record.round_id,
        RecordModelRunRequest(
            candidate_ids=(child.candidate_id,),
            provider="nvidia",
            model="boltz",
            model_version="2",
            execution_mode="nim_inference",
            output_artifact_digests=("sha256:structure",),
        ),
    )
    assert model_run.candidate_ids == (child.candidate_id,)
    assert model_run.scientific_use_allowed is False
    assert len(model_run.input_digest) == 64
    assert len(model_run.parameter_digest) == 64

    caller_marked_scientific = store.record_model_run(
        round_record.round_id,
        RecordModelRunRequest(
            provider="nvidia",
            model="boltz",
            model_version="2",
            execution_mode="nim_inference",
            scientific_use_allowed=True,
        ),
    )
    assert caller_marked_scientific.scientific_use_allowed is False

    job = store.enqueue_model_job(
        campaign.campaign_id,
        EnqueueModelJobRequest(model_run_id=model_run.model_run_id, max_attempts=2),
    )
    claimed = store.claim_model_job("worker-a", job_id=job.job_id)
    assert claimed is not None
    assert claimed.attempt == 1
    assert claimed.lease_owner == "worker-a"
    submitted = store.mark_model_job_submitted(job.job_id, "worker-a", "provider-123")
    assert submitted.provider_request_id == "provider-123"
    finished = store.finish_model_job(job.job_id, "worker-a", ModelJobStatus.SUCCEEDED)
    assert finished.status is ModelJobStatus.SUCCEEDED


def test_training_examples_aggregate_measured_replicates_but_exclude_failures(
    tmp_path: Path,
) -> None:
    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="replicates", objective="test", target_sequence="MKT"
        )
    )
    round_record = store.create_round(
        campaign.campaign_id, CreateRoundRequest(protocol_version="v1")
    )
    candidate = store.add_candidate(
        round_record.round_id, AddCandidateRequest(sequence="ACDE", source="import")
    )
    for value in (1.0, 3.0):
        store.record_measurement(
            round_record.round_id,
            RecordMeasurementRequest(
                candidate_id=candidate.candidate_id,
                metric="binding",
                value=value,
                unit="a.u.",
                method="assay",
                status=AssayStatus.MEASURED,
                replicate=1 if value == 1 else 2,
            ),
        )
    store.record_measurement(
        round_record.round_id,
        RecordMeasurementRequest(
            candidate_id=candidate.candidate_id,
            metric="binding",
            value=None,
            unit="a.u.",
            method="assay",
            status=AssayStatus.FAILED_EXPRESSION,
            replicate=3,
        ),
    )
    dataset = store.freeze_dataset(round_record.round_id, "measured_only")
    examples = store.get_training_examples(dataset.dataset_id, metric="binding")
    assert len(examples) == 1
    assert examples[0].value == 2.0


def test_cross_campaign_parent_and_recommendation_are_rejected(tmp_path: Path) -> None:
    store = CampaignStore(tmp_path)
    first = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="first", objective="test", target_sequence="MKT"
        )
    )
    second = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-b", title="second", objective="test", target_sequence="MKT"
        )
    )
    first_round = store.create_round(first.campaign_id, CreateRoundRequest(protocol_version="v1"))
    second_round = store.create_round(second.campaign_id, CreateRoundRequest(protocol_version="v1"))
    foreign = store.add_candidate(
        second_round.round_id, AddCandidateRequest(sequence="ACDE", source="import")
    )

    with pytest.raises(CampaignConflictError):
        store.add_candidate(
            first_round.round_id,
            AddCandidateRequest(
                sequence="ACDF", source="mutation", parent_ids=(foreign.candidate_id,)
            ),
        )

    with pytest.raises(CampaignConflictError):
        store.create_recommendation(
            first_round.round_id,
            (foreign.candidate_id,),
            policy="greedy",
            evidence_snapshot=(),
            rationale={},
        )


class _FakeConnector:
    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        assert context.model_run.provider == "nvidia"
        return ConnectorResult(
            provider_request_id="request-1", output_artifact_digests=("digest-1",)
        )


def test_model_worker_routes_allowlisted_connector_and_records_output(tmp_path: Path) -> None:
    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="worker", objective="test", target_sequence="MKT"
        )
    )
    round_record = store.create_round(
        campaign.campaign_id, CreateRoundRequest(protocol_version="v1")
    )
    candidate = store.add_candidate(
        round_record.round_id, AddCandidateRequest(sequence="ACDE", source="import")
    )
    model_run = store.record_model_run(
        round_record.round_id,
        RecordModelRunRequest(
            candidate_ids=(candidate.candidate_id,),
            provider="nvidia",
            model="boltz",
            model_version="2",
            execution_mode="nim_inference",
        ),
    )
    job = store.enqueue_model_job(
        campaign.campaign_id, EnqueueModelJobRequest(model_run_id=model_run.model_run_id)
    )
    result = CampaignModelWorker(store, {"nvidia": _FakeConnector()}, owner="worker-a").run_once(
        job_id=job.job_id
    )

    assert result is not None
    assert result.status.value == "succeeded"
    updated = store.get_model_run(model_run.model_run_id)
    assert updated.output_artifact_digests == ("digest-1",)
    assert updated.status is ModelRunStatus.COMPLETED


def test_model_job_budget_cannot_exceed_round_budget(tmp_path: Path) -> None:
    store = CampaignStore(tmp_path)
    campaign = store.create_campaign(
        CreateCampaignRequest(
            organization_id="org-a", title="budget", objective="test", target_sequence="MKT"
        )
    )
    round_record = store.create_round(
        campaign.campaign_id,
        CreateRoundRequest(protocol_version="v1", budget=1.0),
    )
    model_run = store.record_model_run(
        round_record.round_id,
        RecordModelRunRequest(
            provider="nvidia-boltz",
            model="boltz",
            model_version="2",
            execution_mode="nim_inference",
        ),
    )
    with pytest.raises(CampaignConflictError, match="budget"):
        store.enqueue_model_job(
            campaign.campaign_id,
            EnqueueModelJobRequest(model_run_id=model_run.model_run_id, budget_units=2.0),
        )


class _FakeBoltzGateway:
    def predict(self, *, client_id: str, sequence: str) -> NvidiaHostedBoltzResult:
        assert client_id == "campaign-worker"
        assert sequence == "ACDE"
        return NvidiaHostedBoltzResult(
            input_sequence_hash="a" * 64,
            structure_text="ATOM",
            structure_format="pdb",
            elapsed_seconds=0,
            request_artifact_digest="b" * 64,
            response_artifact_digest="c" * 64,
            limitations=("computational hypothesis",),
        )


def test_boltz_connector_adapts_gateway_artifacts() -> None:
    from concordia.campaigns.schema import CampaignModelRun, Candidate, ModelRunStatus, utc_now
    from concordia.campaigns.worker import ModelExecutionContext

    candidate = Candidate(
        candidate_id="candidate-1",
        campaign_id="campaign-1",
        round_id="round-1",
        sequence="ACDE",
        sequence_hash="d" * 64,
        parent_ids=(),
        source="import",
        construct_metadata={},
        created_at=utc_now(),
    )
    model_run = CampaignModelRun(
        model_run_id="run-1",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=(candidate.candidate_id,),
        provider="nvidia-boltz",
        model="boltz",
        model_version="2",
        execution_mode="nim_inference",
        parameters={},
        input_artifact_digests=(),
        output_artifact_digests=(),
        status=ModelRunStatus.QUEUED,
        scientific_use_allowed=False,
        created_at=utc_now(),
    )
    result = BoltzCampaignConnector(_FakeBoltzGateway(), client_id="campaign-worker").execute(
        ModelExecutionContext(model_run=model_run, candidates=(candidate,))
    )
    assert result.output_artifact_digests == ("b" * 64, "c" * 64)
    assert result.provider_request_id.startswith("boltz-response:")


class _FakeBioNeMoRunner:
    def train(
        self,
        *,
        dataset_id: str,
        model: str,
        framework_version: str,
        parameters: dict[str, object],
    ) -> ConnectorResult:
        assert dataset_id == "dataset-1"
        assert model == "esm2"
        assert framework_version == "bionemo-2"
        assert parameters["split_policy"] == "target_family_holdout"
        return ConnectorResult(
            provider_request_id="training-job-1",
            output_artifact_digests=("checkpoint-1", "metrics-1"),
        )


def test_bionemo_training_requires_frozen_dataset_and_returns_artifacts() -> None:
    from concordia.campaigns.schema import CampaignModelRun, ModelRunStatus, utc_now
    from concordia.campaigns.worker import ModelExecutionContext

    run = CampaignModelRun(
        model_run_id="run-training",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=(),
        provider="nvidia-bionemo-framework",
        model="esm2",
        model_version="project-v1",
        execution_mode="private_training",
        parameters={
            "dataset_id": "dataset-1",
            "framework_version": "bionemo-2",
            "split_policy": "target_family_holdout",
        },
        input_artifact_digests=(),
        output_artifact_digests=(),
        status=ModelRunStatus.QUEUED,
        scientific_use_allowed=False,
        created_at=utc_now(),
    )
    result = BioNeMoTrainingConnector(_FakeBioNeMoRunner()).execute(
        ModelExecutionContext(model_run=run, candidates=())
    )
    assert result.output_artifact_digests == ("checkpoint-1", "metrics-1")


def test_http_bionemo_runner_validates_endpoint_and_artifact_only_response() -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "provider_request_id": "job-1",
                "output_artifact_digests": ["checkpoint-1"],
            }

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, *, headers, json):
            self.calls.append((url, headers, json))
            return Response()

    client = Client()
    runner = HttpBioNeMoTrainingRunner("https://bionemo.example", "secret", client=client)
    result = runner.train(
        dataset_id="dataset-1",
        model="esm2",
        framework_version="v1",
        parameters={"seed": 0},
    )
    assert result.provider_request_id == "job-1"
    assert client.calls[0][0] == "https://bionemo.example/train"
    assert "secret" not in str(client.calls[0][2])
    with pytest.raises(ValueError, match="HTTPS"):
        HttpBioNeMoTrainingRunner("http://remote.example", "secret")


def test_bionemo_preflight_checks_authenticated_contract_without_inference() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "service": "bionemo-framework",
                "contract_version": "bionemo-http-v1",
                "status": "ready",
            }

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url, *, headers):
            self.calls.append((url, headers))
            return Response()

    client = Client()
    report = HttpBioNeMoTrainingRunner(
        "https://bionemo.example", "secret", client=client
    ).preflight()
    assert report.ready is True
    assert report.scientific_use_allowed is False
    assert client.calls == [
        (
            "https://bionemo.example/healthz",
            {"Authorization": "Bearer secret", "Accept": "application/json"},
        )
    ]


def test_bionemo_inference_preflight_requires_its_own_service_identity() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "service": "bionemo-framework",
                "contract_version": "bionemo-http-v1",
                "status": "ready",
            }

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url, *, headers):
            self.calls.append((url, headers))
            return Response()

    client = Client()
    report = HttpBioNeMoInferenceRunner(
        "https://bionemo.example", "secret", client=client
    ).preflight()

    assert report.ready is False
    assert report.service == "bionemo-inference"
    assert report.scientific_use_allowed is False
    assert client.calls[0][0] == "https://bionemo.example/healthz"


def test_bionemo_inference_connector_and_http_runner_are_artifact_only() -> None:
    from concordia.campaigns.schema import CampaignModelRun, Candidate, ModelRunStatus, utc_now
    from concordia.campaigns.worker import ModelExecutionContext

    class FakeRunner:
        def infer(self, *, model, sequences, parameters):
            assert model == "esm2"
            assert sequences == ("ACDE",)
            assert parameters["temperature"] == 0.2
            return ConnectorResult(
                provider_request_id="inference-1", output_artifact_digests=("scores-1",)
            )

    candidate = Candidate(
        candidate_id="candidate-inference",
        campaign_id="campaign-1",
        round_id="round-1",
        sequence="ACDE",
        sequence_hash="d" * 64,
        parent_ids=(),
        source="import",
        construct_metadata={},
        created_at=utc_now(),
    )
    run = CampaignModelRun(
        model_run_id="run-inference",
        campaign_id="campaign-1",
        round_id="round-1",
        candidate_ids=(candidate.candidate_id,),
        provider="nvidia-bionemo-inference",
        model="esm2",
        model_version="1",
        execution_mode="nim_inference",
        parameters={"temperature": 0.2},
        input_artifact_digests=(),
        output_artifact_digests=(),
        status=ModelRunStatus.QUEUED,
        scientific_use_allowed=False,
        created_at=utc_now(),
    )
    result = BioNeMoInferenceConnector(FakeRunner()).execute(
        ModelExecutionContext(model_run=run, candidates=(candidate,))
    )
    assert result.output_artifact_digests == ("scores-1",)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"provider_request_id": "job-2", "output_artifact_digests": ["scores-2"]}

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, *, headers, json):
            self.calls.append((url, headers, json))
            return Response()

    client = Client()
    http_runner = HttpBioNeMoInferenceRunner("https://bionemo.example", "secret", client=client)
    http_result = http_runner.infer(
        model="esm2", sequences=("ACDE",), parameters={"temperature": 0.2}
    )
    assert http_result.provider_request_id == "job-2"
    assert client.calls[0][0] == "https://bionemo.example/infer"
    assert client.calls[0][2]["sequences"] == ["ACDE"]
