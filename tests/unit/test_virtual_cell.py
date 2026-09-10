from pathlib import Path

import pytest

from concordia.storage.content import ContentAddressedStore
from concordia.virtual_cell import (
    RecordedStateFixtureRunner,
    StateInputArtifact,
    StatePerturbation,
    StatePredictionRequest,
    StateResourceBudget,
    StateSandbox,
)


def request(store: ContentAddressedStore) -> StatePredictionRequest:
    adata = store.put_bytes(b"recorded fixture, not an AnnData scientific input")
    return StatePredictionRequest(
        request_id="state-fixture-1",
        model_id="arc-state-contract-fixture",
        checkpoint_digest="a" * 64,
        input=StateInputArtifact(
            adata_digest=adata,
            cell_count=8,
            gene_count=16,
            gene_order_digest="b" * 64,
            preprocessing_version="fixture-v1",
            cell_context_key="cell_type",
            perturbation_key="target_gene",
        ),
        perturbation=StatePerturbation(kind="genetic", identifier="GENE_FIXTURE"),
        cell_context="fixture-cell-context",
    )


def test_state_sandbox_persists_request_and_blocks_fixture_science(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "artifacts")
    result = StateSandbox(store, RecordedStateFixtureRunner()).execute(request(store))

    assert result.execution_mode == "recorded_fixture"
    assert not result.scientific_use_allowed
    assert store.get_bytes(result.request_artifact_digest)
    assert store.get_bytes(result.prediction_artifact_digest)


def test_state_request_enforces_population_resource_budget(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "artifacts")
    value = request(store).model_dump(mode="json")
    value["budget"] = StateResourceBudget(max_cells=4).model_dump(mode="json")

    with pytest.raises(ValueError, match="cell count"):
        StatePredictionRequest.model_validate(value)


def test_state_sandbox_rejects_missing_input_artifact(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "artifacts")
    value = request(store).model_dump(mode="json")
    value["input"]["adata_digest"] = "f" * 64

    with pytest.raises(FileNotFoundError):
        StateSandbox(store, RecordedStateFixtureRunner()).execute(
            StatePredictionRequest.model_validate(value)
        )
