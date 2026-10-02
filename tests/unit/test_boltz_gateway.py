from __future__ import annotations

import pytest

from concordia.genomics.boltz_gateway import BoltzGateway, RateLimitExceededError
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzResult


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, sequence: str) -> NvidiaHostedBoltzResult:
        self.calls += 1
        return NvidiaHostedBoltzResult(
            input_sequence_hash="0" * 64,
            structure_text="ATOM stub",
            structure_format="pdb",
            elapsed_seconds=0.01,
            request_artifact_digest="1" * 64,
            response_artifact_digest="2" * 64,
            limitations=("test",),
        )


def test_identical_sequences_are_served_from_cache(tmp_path) -> None:
    runner = FakeRunner()
    gateway = BoltzGateway(runner, database_path=tmp_path / "boltz.sqlite3", clock=FakeClock())

    first = gateway.predict(client_id="1.2.3.4", sequence="MKT")
    second = gateway.predict(client_id="1.2.3.4", sequence="mkt")

    assert runner.calls == 1
    assert first == second


def test_per_client_rate_limit_is_enforced(tmp_path) -> None:
    runner = FakeRunner()
    gateway = BoltzGateway(
        runner, database_path=tmp_path / "boltz.sqlite3", per_client_limit=1, clock=FakeClock()
    )

    gateway.predict(client_id="1.2.3.4", sequence="AAA")
    with pytest.raises(RateLimitExceededError):
        gateway.predict(client_id="1.2.3.4", sequence="CCC")

    gateway.predict(client_id="5.6.7.8", sequence="DDD")
