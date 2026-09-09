"""Bounded local worker for leased run execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from concordia.runtime.contracts import RunRecord, RunStatus
from concordia.runtime.service import ArtifactExecutionError, RunService
from concordia.runtime.state_machine import TERMINAL_STATES
from concordia.scheduling.jobs import JobLease, JobState


class InfrastructureFailure(RuntimeError):
    """An explicitly retryable failure in local execution infrastructure."""


@dataclass(frozen=True)
class LocalWorker:
    service: RunService
    owner: str
    lease_seconds: float = 30

    @classmethod
    def create(cls, service: RunService, owner: str | None = None) -> LocalWorker:
        return cls(service=service, owner=owner or f"worker-{uuid.uuid4()}")

    def run_once(
        self, *, run_id: str | None = None, now: datetime | None = None
    ) -> RunRecord | None:
        self.recover_exhausted(now=now)
        lease = self.service.jobs.claim(
            self.owner,
            lease_seconds=self.lease_seconds,
            now=now,
            run_id=run_id,
        )
        if lease is None:
            return None
        return self.execute(lease)

    def execute(self, lease: JobLease) -> RunRecord:
        try:
            record = self.service.execute_leased(lease)
        except InfrastructureFailure as error:
            current = self.service.get_run(lease.run_id)
            will_retry = lease.attempt < lease.max_attempts
            self.service.ledger.append(
                lease.run_id,
                "INFRASTRUCTURE_FAILURE_RECORDED",
                {
                    "attempt": lease.attempt,
                    "max_attempts": lease.max_attempts,
                    "retry_scheduled": will_retry,
                    "error_type": type(error).__name__,
                },
                expected_sequence=current.last_sequence_number,
            )
            exhausted = self.service.jobs.release_infrastructure_failure(lease)
            if exhausted:
                self.service.transition(
                    lease.run_id,
                    RunStatus.FAILED_TOOL,
                    reason="retryable infrastructure failure exhausted",
                )
            raise
        except ArtifactExecutionError as error:
            record = self.service.transition(
                lease.run_id, RunStatus.FAILED_ARTIFACT, reason=str(error)
            )
            self.service.jobs.finish(lease, JobState.FAILED)
            return record
        except ValueError as error:
            record = self.service.transition(
                lease.run_id, RunStatus.FAILED_VALIDATION, reason=str(error)
            )
            self.service.jobs.finish(lease, JobState.FAILED)
            return record
        except Exception as error:
            record = self.service.get_run(lease.run_id)
            if record.current_status not in TERMINAL_STATES:
                self.service.transition(
                    lease.run_id,
                    RunStatus.FAILED_TOOL,
                    reason=f"unhandled tool failure: {type(error).__name__}",
                )
            self.service.jobs.finish(lease, JobState.FAILED)
            raise
        terminal_state = (
            JobState.CANCELLED
            if record.current_status is RunStatus.CANCELLED
            else JobState.DONE
            if record.current_status is RunStatus.COMPLETED
            else JobState.FAILED
        )
        self.service.jobs.finish(lease, terminal_state)
        return record

    def recover_exhausted(self, *, now: datetime | None = None) -> tuple[str, ...]:
        run_ids = self.service.jobs.exhausted_expired(now=now)
        for run_id in run_ids:
            record = self.service.get_run(run_id)
            if record.current_status not in TERMINAL_STATES:
                self.service.transition(
                    run_id,
                    RunStatus.TIMED_OUT,
                    reason="worker lease expired after maximum attempts",
                )
        return run_ids
