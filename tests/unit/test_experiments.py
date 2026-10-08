from __future__ import annotations

import json
from pathlib import Path

import pytest

from concordia.experiments.schema import (
    CreateExperimentNodeRequest,
    CreateExperimentRequest,
    DnaPayload,
    ExperimentNodeKind,
    ExperimentOperation,
    MeasurementPayload,
    ModelRunPayload,
    MutationRecord,
)
from concordia.experiments.service import (
    ExperimentAccessError,
    ExperimentConflictError,
    ExperimentStore,
)


def test_experiment_dag_branches_compares_selects_and_replays(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    created = store.create(
        CreateExperimentRequest(title="TP53 counterfactuals", description="Bounded sandbox")
    )
    experiment_id = created.experiment.experiment_id
    store.authorize(experiment_id, created.access_token)

    root = store.add_node(
        experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.DNA_SEQUENCE,
            operation=ExperimentOperation.ROOT,
            label="TP53 reference",
            payload=DnaPayload(sequence="ACGT"),
        ),
    )
    variant = store.add_node(
        experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.DNA_SEQUENCE,
            operation=ExperimentOperation.MUTATE,
            label="Variant A",
            branch="variant-a",
            parent_ids=(root.node_id,),
            payload=DnaPayload(sequence="ATGT"),
            mutations=(MutationRecord(position=1, reference="C", alternate="T"),),
        ),
    )
    alternative = store.add_node(
        experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.DNA_SEQUENCE,
            operation=ExperimentOperation.GENERATE,
            label="Generated B",
            branch="generated-b",
            parent_ids=(root.node_id,),
            payload=DnaPayload(sequence="ACGA"),
        ),
    )

    comparison = store.compare(experiment_id, variant.node_id, alternative.node_id)
    assert comparison.comparable is True
    assert comparison.differing_positions == (1, 3)
    assert comparison.length_delta == 0

    manifest = store.select(experiment_id, variant.node_id)
    assert manifest.selected_candidate_ids == (variant.node_id,)
    assert len(manifest.nodes) == 3
    assert {(edge.parent_id, edge.child_id) for edge in manifest.edges} == {
        (root.node_id, variant.node_id),
        (root.node_id, alternative.node_id),
    }
    assert store.manifest(experiment_id).manifest_digest == manifest.manifest_digest


def test_node_payload_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    created = store.create(CreateExperimentRequest(title="Scores"))
    node = store.add_node(
        created.experiment.experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.MEASUREMENT,
            operation=ExperimentOperation.ROOT,
            label="Baseline score",
            payload=MeasurementPayload(
                metric="mean_log_likelihood", value=-0.42, method="fixture"
            ),
        ),
    )

    payload = json.loads(store.artifacts.get_bytes(node.artifact_digest))
    assert payload["metric"] == "mean_log_likelihood"
    assert payload["value"] == -0.42


def test_cross_experiment_parent_is_rejected(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    first = store.create(CreateExperimentRequest(title="First"))
    second = store.create(CreateExperimentRequest(title="Second"))
    root = store.add_node(
        first.experiment.experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.DNA_SEQUENCE,
            operation=ExperimentOperation.ROOT,
            label="Root",
            payload=DnaPayload(sequence="ACGT"),
        ),
    )

    with pytest.raises(ExperimentConflictError, match="every parent"):
        store.add_node(
            second.experiment.experiment_id,
            CreateExperimentNodeRequest(
                kind=ExperimentNodeKind.DNA_SEQUENCE,
                operation=ExperimentOperation.EDIT,
                label="Invalid child",
                parent_ids=(root.node_id,),
                payload=DnaPayload(sequence="ACGA"),
            ),
        )


def test_access_token_is_required_and_not_in_manifest(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    created = store.create(CreateExperimentRequest(title="Private"))

    with pytest.raises(ExperimentAccessError):
        store.authorize(created.experiment.experiment_id, "wrong-token")

    manifest_json = store.manifest(created.experiment.experiment_id).model_dump_json()
    assert created.access_token not in manifest_json
    assert "access_token" not in manifest_json


def test_model_run_and_output_are_recorded_as_one_lineage_step(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    created = store.create(CreateExperimentRequest(title="Evo2 generation"))
    experiment_id = created.experiment.experiment_id
    root = store.add_node(
        experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.DNA_SEQUENCE,
            operation=ExperimentOperation.ROOT,
            label="Seed DNA",
            payload=DnaPayload(sequence="ACGT"),
        ),
    )

    run, output = store.record_model_operation(
        experiment_id,
        parent_node_id=root.node_id,
        branch="candidate-a",
        run_label="Evo2 generation",
        run_payload=ModelRunPayload(
            model="arc/evo2-40b",
            model_version="arc/evo2-40b",
            parameters={"temperature": 0.7},
            seed=1729,
            execution_mode="real_hosted_generation",
        ),
        output_label="Generated DNA",
        output_kind=ExperimentNodeKind.DNA_SEQUENCE,
        output_payload=DnaPayload(sequence="TGCA"),
        operation=ExperimentOperation.GENERATE,
        evidence_artifact_digests=("a" * 64, "b" * 64),
    )

    manifest = store.manifest(experiment_id)
    assert [node.node_id for node in manifest.nodes] == [root.node_id, run.node_id, output.node_id]
    assert {(edge.parent_id, edge.child_id) for edge in manifest.edges} == {
        (root.node_id, run.node_id),
        (run.node_id, output.node_id),
    }
    assert run.kind == ExperimentNodeKind.MODEL_RUN
    assert output.scientific_use_allowed is False
