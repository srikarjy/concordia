from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from concordia.genomics.schema import GenomicSequence
from concordia.runtime.contracts import RunStatus
from concordia.runtime.service import CreateRunRequest, RunService
from concordia.runtime.worker import InfrastructureFailure, LocalWorker
from concordia.scheduling.jobs import JobState, LeaseConflictError


def fixture_request(key: str = "worker-fixture-1") -> CreateRunRequest:
    return CreateRunRequest(
        idempotency_key=key,
        sequence=GenomicSequence(
            sequence_id="fixture:worker-sequence",
            sequence="ACGTTGCAACGT",
            assembly="GRCh38",
            region="chr1:0-12",
            strand="+",
        ),
        scan_position=4,
    )


def test_worker_claims_and_completes_a_scheduled_run(tmp_path) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())
    assert scheduled.current_status is RunStatus.SCHEDULED

    completed = LocalWorker.create(service, "worker-1").run_once()

    assert completed is not None
    assert completed.current_status is RunStatus.COMPLETED
    assert service.jobs.get(scheduled.spec.run_id).state is JobState.DONE


def test_stale_lease_is_recovered_by_another_worker(tmp_path) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())
    claimed_at = datetime.now(UTC)
    first = service.jobs.claim(
        "crashed-worker", run_id=scheduled.spec.run_id, lease_seconds=1, now=claimed_at
    )
    assert first is not None
    service.transition(scheduled.spec.run_id, RunStatus.EXECUTING)
    assert service.jobs.claim(
        "early-worker", run_id=scheduled.spec.run_id, now=claimed_at
    ) is None

    recovered = service.jobs.claim(
        "recovery-worker",
        run_id=scheduled.spec.run_id,
        lease_seconds=30,
        now=claimed_at + timedelta(seconds=2),
    )
    assert recovered is not None
    assert recovered.attempt == 2

    completed = LocalWorker.create(service, "recovery-worker").execute(recovered)
    assert completed.current_status is RunStatus.COMPLETED


def test_heartbeat_requires_the_current_unexpired_owner(tmp_path) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())
    claimed_at = datetime.now(UTC)
    lease = service.jobs.claim(
        "worker-1", run_id=scheduled.spec.run_id, lease_seconds=10, now=claimed_at
    )
    assert lease is not None

    extended = service.jobs.heartbeat(
        lease, lease_seconds=20, now=claimed_at + timedelta(seconds=1)
    )
    assert extended.expires_at == claimed_at + timedelta(seconds=21)
    with pytest.raises(LeaseConflictError):
        service.jobs.heartbeat(lease, now=claimed_at + timedelta(seconds=30))


def test_cancelled_job_cannot_be_claimed(tmp_path) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())

    cancelled = service.cancel(scheduled.spec.run_id)

    assert cancelled.current_status is RunStatus.CANCELLED
    assert service.cancel(scheduled.spec.run_id) == cancelled
    assert service.jobs.get(scheduled.spec.run_id).state is JobState.CANCELLED
    assert LocalWorker.create(service, "worker-1").run_once() is None


def test_corrupt_input_artifact_is_preserved_as_failed_artifact(tmp_path) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())
    artifact_path = service.artifacts.path_for(scheduled.spec.task.sequence_artifact_id)
    artifact_path.write_bytes(b"corrupt")

    failed = LocalWorker.create(service, "worker-1").run_once()

    assert failed is not None
    assert failed.current_status is RunStatus.FAILED_ARTIFACT
    assert failed.terminal_reason == "input artifact failed integrity validation"
    assert service.jobs.get(scheduled.spec.run_id).state is JobState.FAILED


def test_only_explicit_infrastructure_failures_are_retried(tmp_path, monkeypatch) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())
    worker = LocalWorker.create(service, "worker-1")

    def fail_infrastructure(_lease):  # type: ignore[no-untyped-def]
        raise InfrastructureFailure("temporary local executor failure")

    monkeypatch.setattr(service, "execute_leased", fail_infrastructure)
    with pytest.raises(InfrastructureFailure):
        worker.run_once()

    job = service.jobs.get(scheduled.spec.run_id)
    assert job.state is JobState.QUEUED
    assert job.attempts == 1
    assert service.get_run(scheduled.spec.run_id).current_status is RunStatus.SCHEDULED
    failure_events = [
        event
        for event in service.ledger.all_events(scheduled.spec.run_id)
        if event.event_type == "INFRASTRUCTURE_FAILURE_RECORDED"
    ]
    assert failure_events[0].payload["retry_scheduled"] is True


def test_exhausted_crashed_lease_becomes_timed_out(tmp_path) -> None:
    service = RunService.local(tmp_path)
    request = fixture_request().model_copy(update={"max_infrastructure_attempts": 1})
    scheduled = service.create_scheduled(request)
    claimed_at = datetime.now(UTC)
    lease = service.jobs.claim(
        "crashed-worker", run_id=scheduled.spec.run_id, lease_seconds=1, now=claimed_at
    )
    assert lease is not None

    recovered = LocalWorker.create(service, "recovery-worker").recover_exhausted(
        now=claimed_at + timedelta(seconds=2)
    )

    assert recovered == (scheduled.spec.run_id,)
    record = service.get_run(scheduled.spec.run_id)
    assert record.current_status is RunStatus.TIMED_OUT
    assert service.jobs.get(scheduled.spec.run_id).state is JobState.FAILED


def test_restart_repairs_a_scheduled_run_missing_its_operational_job(tmp_path) -> None:
    service = RunService.local(tmp_path)
    scheduled = service.create_scheduled(fixture_request())
    with service.jobs._connect() as connection:
        connection.execute("DELETE FROM jobs WHERE run_id = ?", (scheduled.spec.run_id,))

    restarted = RunService.local(tmp_path)

    assert restarted.jobs.get(scheduled.spec.run_id).state is JobState.QUEUED
    completed = LocalWorker.create(restarted, "recovery-worker").run_once()
    assert completed is not None
    assert completed.current_status is RunStatus.COMPLETED
