from __future__ import annotations

import pytest

from concordia.genomics.evo2_generation_gateway import (
    Evo2GenerationGateway,
    RateLimitExceededError,
)
from concordia.genomics.evo2_nvidia import NvidiaHostedGenerationResult
from concordia.genomics.schema import GenomicSequence


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, sequence: GenomicSequence, **kwargs) -> NvidiaHostedGenerationResult:
        self.calls += 1
        return NvidiaHostedGenerationResult(
            input_sequence_hash=sequence.content_hash(),
            generated_sequence="A" * kwargs.get("num_tokens", 8),
            sampled_probabilities=tuple(0.5 for _ in range(kwargs.get("num_tokens", 8))),
            elapsed_seconds=0.01,
            request_artifact_digest="0" * 64,
            response_artifact_digest="1" * 64,
            limitations=("test limitation",),
        )


def sequence() -> GenomicSequence:
    return GenomicSequence(sequence_id="interactive:test", sequence="ACGT", strand="+")


def test_identical_requests_are_served_from_cache(tmp_path) -> None:
    runner = FakeRunner()
    gateway = Evo2GenerationGateway(
        runner, database_path=tmp_path / "gen.sqlite3", clock=FakeClock()
    )

    first = gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=4)
    second = gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=4)

    assert runner.calls == 1
    assert first == second


def test_per_client_rate_limit_is_enforced(tmp_path) -> None:
    runner = FakeRunner()
    clock = FakeClock()
    gateway = Evo2GenerationGateway(
        runner,
        database_path=tmp_path / "gen.sqlite3",
        per_client_limit=2,
        clock=clock,
    )

    gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=1)
    gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=2)
    with pytest.raises(RateLimitExceededError):
        gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=3)

    # A different client is unaffected by another client's usage.
    gateway.generate(client_id="5.6.7.8", sequence=sequence(), num_tokens=1)


def test_global_daily_limit_is_enforced_across_clients(tmp_path) -> None:
    runner = FakeRunner()
    clock = FakeClock()
    gateway = Evo2GenerationGateway(
        runner,
        database_path=tmp_path / "gen.sqlite3",
        per_client_limit=10,
        global_daily_limit=2,
        clock=clock,
    )

    gateway.generate(client_id="1.1.1.1", sequence=sequence(), num_tokens=1)
    gateway.generate(client_id="2.2.2.2", sequence=sequence(), num_tokens=2)
    with pytest.raises(RateLimitExceededError):
        gateway.generate(client_id="3.3.3.3", sequence=sequence(), num_tokens=3)


def test_rate_limit_window_resets_after_elapsed_time(tmp_path) -> None:
    runner = FakeRunner()
    clock = FakeClock()
    gateway = Evo2GenerationGateway(
        runner,
        database_path=tmp_path / "gen.sqlite3",
        per_client_limit=1,
        per_client_window_seconds=60,
        clock=clock,
    )

    gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=1)
    with pytest.raises(RateLimitExceededError):
        gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=2)

    clock.now += 61
    gateway.generate(client_id="1.2.3.4", sequence=sequence(), num_tokens=3)
