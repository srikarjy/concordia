"""Real-input, fixture-output virtual-cell demonstration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from concordia.storage.content import ContentAddressedStore
from concordia.virtual_cell.cellxgene import (
    AnndataH5adInspector,
    CellxgeneDatasetSource,
    CellxgeneDiscoverIngestor,
)
from concordia.virtual_cell.contracts import (
    StateInputArtifact,
    StatePerturbation,
    StatePredictionRequest,
    StateResourceBudget,
)
from concordia.virtual_cell.sandbox import RecordedStateFixtureRunner, StateSandbox


def run_cellxgene_state_demo(
    state_root: str | Path,
    source_manifest: str | Path,
) -> dict[str, Any]:
    """Ingest one frozen real H5AD and exercise State contracts without predictions."""
    root = Path(state_root)
    artifacts = ContentAddressedStore(root / "artifacts")
    manifest_payload = yaml.safe_load(Path(source_manifest).read_text(encoding="utf-8"))
    source = CellxgeneDatasetSource.model_validate(manifest_payload)
    ingestion = CellxgeneDiscoverIngestor(
        artifacts,
        AnndataH5adInspector(),
    ).ingest(source)
    checkpoint_digest = artifacts.put_json(
        {
            "schema_version": 1,
            "kind": "state-checkpoint-absence-marker",
            "contains_model_weights": False,
            "scientific_use_allowed": False,
        }
    )
    state_input = StateInputArtifact(
        adata_digest=ingestion.adata_artifact_digest,
        cell_count=ingestion.summary.cell_count,
        gene_count=ingestion.summary.gene_count,
        gene_order_digest=ingestion.summary.gene_order_digest,
        preprocessing_version=(
            f"cellxgene-schema-{ingestion.summary.h5ad_schema_version}-unmodified-X"
        ),
        cell_context_key=source.cell_context_key,
        perturbation_key=source.perturbation_key,
        gene_identifier_key="var_names",
        feature_matrix_key="X",
        source_dataset_id=source.dataset_id,
        source_dataset_version_id=source.dataset_version_id,
    )
    request = StatePredictionRequest(
        request_id=f"cellxgene-state-contract-{source.dataset_version_id}",
        model_id="arc-state-contract-fixture-no-weights",
        checkpoint_digest=checkpoint_digest,
        input=state_input,
        perturbation=StatePerturbation(kind="genetic", identifier="SBE1/5"),
        cell_context="neural progenitor cell",
        budget=StateResourceBudget(
            max_cells=2_000,
            max_genes=40_000,
            memory_megabytes=8_192,
            output_bytes=100_000_000,
        ),
    )
    prediction = StateSandbox(artifacts, RecordedStateFixtureRunner()).execute(request)
    report = {
        "schema_version": 1,
        "input": ingestion.model_dump(mode="json"),
        "state_request": request.model_dump(mode="json"),
        "state_result": prediction.model_dump(mode="json"),
        "execution_mode": "real_input_recorded_fixture_output",
        "scientific_use_allowed": False,
        "limitations": [
            "The CELLxGENE input is real and checksum validated.",
            "No State checkpoint was loaded and no cellular prediction was produced.",
            "Checkpoint feature-space compatibility remains unqualified.",
        ],
    }
    report_digest = artifacts.put_json(report)
    envelope = {"report_artifact_digest": report_digest, "report": report}
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / "cellxgene-state-demo.json.tmp"
    target = root / "cellxgene-state-demo.json"
    temporary.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return envelope
