from __future__ import annotations

import threading
import time

import pytest

from concordia.genomics.evo2_forward_queue import (
    Evo2ForwardJobQueue,
    QueueBusyError,
    RateLimitExceededError,
)
from concordia.genomics.schema import GenomicSequence

CHECKPOINT = "arcinstitute/evo2_7b@test/evo2_7b.pt"
TARGET = "mean_next_base_log_likelihood"


class FakeScorer:
    def __init__(self, *, delay_seconds: float = 0.0, fail: bool = False) -> None:
        self.delay_seconds = delay_seconds
        self.fail = fail
        self.calls = 0

    def score(self, sequence: GenomicSequence, **kwargs) -> dict:
        self.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("synthetic forward-pass failure")
        return {"model_id": CHECKPOINT, "score": -0.01, "target": TARGET}


def sequence() -> GenomicSequence:
    return GenomicSequence(sequence_id="test:window", sequence="ACGT" * 2048, strand="+")


def test_successful_job_records_completed_result(tmp_path) -> None:
    scorer = FakeScorer()
    queue = Evo2ForwardJobQueue(
        scorer, database_path=tmp_path / "jobs.sqlite3", checkpoint=CHECKPOINT, target=TARGET
    )
    job_id = queue.submit(client_id="1.2.3.4", sequence=sequence())
    queue.run(job_id, sequence())

    record = queue.get(job_id)
    assert record["status"] == "COMPLETED"
    assert record["result"]["score"] == -0.01


def test_failed_scoring_is_recorded_not_raised_to_caller(tmp_path) -> None:
    scorer = FakeScorer(fail=True)
    queue = Evo2ForwardJobQueue(
        scorer, database_path=tmp_path / "jobs.sqlite3", checkpoint=CHECKPOINT, target=TARGET
    )
    job_id = queue.submit(client_id="1.2.3.4", sequence=sequence())
    queue.run(job_id, sequence())

    record = queue.get(job_id)
    assert record["status"] == "FAILED"
    assert "synthetic forward-pass failure" in record["error"]


def test_concurrent_run_is_rejected_as_busy(tmp_path) -> None:
    scorer = FakeScorer(delay_seconds=0.3)
    queue = Evo2ForwardJobQueue(
        scorer, database_path=tmp_path / "jobs.sqlite3", checkpoint=CHECKPOINT, target=TARGET
    )
    first_job = queue.submit(client_id="1.1.1.1", sequence=sequence())
    second_job = queue.submit(client_id="2.2.2.2", sequence=sequence())

    thread = threading.Thread(target=queue.run, args=(first_job, sequence()))
    thread.start()
    time.sleep(0.05)
    with pytest.raises(QueueBusyError):
        queue.run(second_job, sequence())
    thread.join()

    assert queue.get(first_job)["status"] == "COMPLETED"
    assert queue.get(second_job)["status"] == "REJECTED_BUSY"
    assert scorer.calls == 1


def test_per_client_submit_rate_limit_is_enforced(tmp_path) -> None:
    scorer = FakeScorer()
    queue = Evo2ForwardJobQueue(
        scorer,
        database_path=tmp_path / "jobs.sqlite3",
        checkpoint=CHECKPOINT,
        target=TARGET,
        per_client_limit=1,
    )
    queue.submit(client_id="1.2.3.4", sequence=sequence())
    with pytest.raises(RateLimitExceededError):
        queue.submit(client_id="1.2.3.4", sequence=sequence())

    # A different client is unaffected.
    queue.submit(client_id="5.6.7.8", sequence=sequence())
