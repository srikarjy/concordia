"""Persist-first, fail-closed State execution boundary."""

from __future__ import annotations

import hashlib
from typing import Protocol

from concordia.storage.content import ContentAddressedStore
from concordia.virtual_cell.contracts import StatePredictionRequest, StatePredictionResult


class StateRunner(Protocol):
    def predict(
        self,
        request: StatePredictionRequest,
        request_artifact_digest: str,
        artifacts: ContentAddressedStore,
    ) -> StatePredictionResult: ...


class StateSandbox:
    """Validate immutable identities and output integrity around an approved runner."""

    def __init__(self, artifacts: ContentAddressedStore, runner: StateRunner):
        self.artifacts = artifacts
        self.runner = runner

    def execute(self, request: StatePredictionRequest) -> StatePredictionResult:
        self.artifacts.get_bytes(request.input.adata_digest)
        request_digest = self.artifacts.put_json(request.model_dump(mode="json"))
        result = self.runner.predict(request, request_digest, self.artifacts)
        if result.request_id != request.request_id:
            raise ValueError("State result request identity does not match")
        if result.request_artifact_digest != request_digest:
            raise ValueError("State result does not reference the persisted request")
        if result.model_id != request.model_id:
            raise ValueError("State result model identity does not match")
        if result.checkpoint_digest != request.checkpoint_digest:
            raise ValueError("State result checkpoint identity does not match")
        if result.input_adata_digest != request.input.adata_digest:
            raise ValueError("State result input identity does not match")
        if result.output_cell_count != request.input.cell_count:
            raise ValueError("State result cell count does not match the request")
        if result.output_gene_count != request.input.gene_count:
            raise ValueError("State result gene count does not match the request")
        self.artifacts.get_bytes(result.prediction_artifact_digest)
        return result


class RecordedStateFixtureRunner:
    """Runnable contract fixture; it creates no biological predictions."""

    def predict(
        self,
        request: StatePredictionRequest,
        request_artifact_digest: str,
        artifacts: ContentAddressedStore,
    ) -> StatePredictionResult:
        marker = hashlib.sha256(
            f"{request.request_id}:{request.input.adata_digest}".encode()
        ).hexdigest()
        prediction_digest = artifacts.put_json(
            {
                "schema_version": 1,
                "fixture_marker": marker,
                "shape": [request.input.cell_count, request.input.gene_count],
                "contains_predictions": False,
                "scientific_use_allowed": False,
            }
        )
        return StatePredictionResult(
            request_id=request.request_id,
            request_artifact_digest=request_artifact_digest,
            model_id=request.model_id,
            checkpoint_digest=request.checkpoint_digest,
            input_adata_digest=request.input.adata_digest,
            prediction_artifact_digest=prediction_digest,
            output_cell_count=request.input.cell_count,
            output_gene_count=request.input.gene_count,
            execution_mode="recorded_fixture",
            scientific_use_allowed=False,
            limitations=(
                "Software fixture only; no State weights or cellular predictions were used.",
            ),
        )
