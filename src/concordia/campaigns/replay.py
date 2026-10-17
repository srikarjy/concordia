"""Explicit replay contracts for campaign model runs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from concordia.campaigns.schema import CampaignModelRun, ModelRunStatus


class ReplayMode(StrEnum):
    READ = "replay_read"
    EXECUTE = "replay_execute"


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ReplayMode
    source_model_run_id: str
    model_run_id: str
    exact: bool
    drift_detected: bool | None
    output_artifact_digests: tuple[str, ...]
    limitations: tuple[str, ...]


def replay_read(run: CampaignModelRun) -> ReplayResult:
    """Return the recorded result without invoking a provider."""
    exact = run.status is ModelRunStatus.COMPLETED and bool(run.output_artifact_digests)
    return ReplayResult(
        mode=ReplayMode.READ,
        source_model_run_id=run.model_run_id,
        model_run_id=run.model_run_id,
        exact=exact,
        drift_detected=False if exact else None,
        output_artifact_digests=run.output_artifact_digests,
        limitations=(
            "replay-read reproduces recorded artifact references; it does not rerun a model",
        )
        if exact
        else ("completed model run has no persisted output artifacts",),
    )


def replay_execute(source: CampaignModelRun, replay: CampaignModelRun) -> ReplayResult:
    """Describe a fresh execution; it is never treated as exact replay."""
    return ReplayResult(
        mode=ReplayMode.EXECUTE,
        source_model_run_id=source.model_run_id,
        model_run_id=replay.model_run_id,
        exact=False,
        drift_detected=None,
        output_artifact_digests=replay.output_artifact_digests,
        limitations=(
            "replay-execute is a new observation and may drift with provider or environment",
            "scientific eligibility remains false until independent validation",
        ),
    )


__all__ = ["ReplayMode", "ReplayResult", "replay_execute", "replay_read"]
