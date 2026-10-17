"""Allow-listed worker boundary for campaign model connectors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from concordia.campaigns.schema import (
    CampaignModelJob,
    CampaignModelRun,
    Candidate,
    ModelJobStatus,
    ModelRunStatus,
)
from concordia.campaigns.service import CampaignStore


class ConnectorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_request_id: str = Field(min_length=1, max_length=500)
    output_artifact_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=100)


class ModelExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_run: CampaignModelRun
    candidates: tuple[Candidate, ...]


class ModelConnector(Protocol):
    def execute(self, context: ModelExecutionContext) -> ConnectorResult: ...


class ModelConnectorError(RuntimeError):
    pass


class CampaignModelWorker:
    """Claims one job and runs only a connector explicitly registered by provider."""

    def __init__(
        self,
        store: CampaignStore,
        connectors: Mapping[str, ModelConnector],
        *,
        owner: str,
        lease_seconds: float = 60,
    ):
        self.store = store
        self.connectors = connectors
        self.owner = owner
        self.lease_seconds = lease_seconds

    def run_once(self, *, job_id: str | None = None) -> CampaignModelJob | None:
        job = self.store.claim_model_job(
            self.owner, lease_seconds=self.lease_seconds, job_id=job_id
        )
        if job is None:
            return None
        model_run = self.store.get_model_run(job.model_run_id)
        candidates = tuple(
            self.store.get_candidate(candidate_id) for candidate_id in model_run.candidate_ids
        )
        context = ModelExecutionContext(model_run=model_run, candidates=candidates)
        connector = self.connectors.get(model_run.provider)
        if connector is None:
            self.store.complete_model_run(
                model_run.model_run_id,
                output_artifact_digests=(),
                status=ModelRunStatus.FAILED,
            )
            return self.store.finish_model_job(job.job_id, self.owner, ModelJobStatus.FAILED)
        try:
            result = connector.execute(context)
            self.store.mark_model_job_submitted(job.job_id, self.owner, result.provider_request_id)
            self.store.complete_model_run(
                model_run.model_run_id,
                output_artifact_digests=result.output_artifact_digests,
            )
            return self.store.finish_model_job(job.job_id, self.owner, ModelJobStatus.SUCCEEDED)
        except Exception as error:
            if job.attempt < job.max_attempts:
                self.store.retry_model_job(job.job_id, self.owner)
            else:
                self.store.complete_model_run(
                    model_run.model_run_id,
                    output_artifact_digests=(),
                    status=ModelRunStatus.FAILED,
                )
                self.store.finish_model_job(job.job_id, self.owner, ModelJobStatus.FAILED)
            raise ModelConnectorError(type(error).__name__) from error


__all__ = [
    "CampaignModelWorker",
    "ConnectorResult",
    "ModelExecutionContext",
    "ModelConnector",
    "ModelConnectorError",
]
