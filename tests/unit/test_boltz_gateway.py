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

    def preflight(self, sequence: str | None = None) -> None:
        if sequence is not None and not sequence.isalpha():
            raise ValueError("sequence contains invalid characters")

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


def test_rejected_input_does_not_consume_quota(tmp_path) -> None:
    runner = FakeRunner()
    gateway = BoltzGateway(
        runner, database_path=tmp_path / "boltz.sqlite3", per_client_limit=1, clock=FakeClock()
    )

    with pytest.raises(ValueError):
        gateway.predict(client_id="1.2.3.4", sequence="MK1")

    gateway.predict(client_id="1.2.3.4", sequence="MKT")
    assert runner.calls == 1


@pytest.mark.parametrize(
    "overrides",
    [{"diffusion_samples": 5, "sampling_steps": 200}, {"recycling_steps": 10}],
)
def test_public_complex_calls_are_capped_before_any_quota_or_compute(tmp_path, overrides) -> None:
    from concordia.genomics.boltz_nvidia import BoltzComplexRequest

    runner = FakeRunner()
    gateway = BoltzGateway(runner, database_path=tmp_path / "boltz.sqlite3", clock=FakeClock())
    request = BoltzComplexRequest(
        polymers=(
            {"id": "H", "molecule_type": "protein", "sequence": "EVQLV"},
            {"id": "A", "molecule_type": "protein", "sequence": "MKTAY"},
        ),
        **overrides,
    )
    with pytest.raises(ValueError, match="exceeds this endpoint's limit"):
        gateway.predict_complex(client_id="1.2.3.4", request=request)
    assert runner.calls == 0


def test_public_complex_request_size_is_capped(tmp_path) -> None:
    from concordia.genomics.boltz_nvidia import BoltzComplexRequest

    gateway = BoltzGateway(
        FakeRunner(), database_path=tmp_path / "boltz.sqlite3", max_request_bytes=2_000
    )
    huge_msa = {"uniref90": {"a3m": {"alignment": ">q\n" + "A" * 5_000, "format": "a3m"}}}
    request = BoltzComplexRequest(
        polymers=(
            {"id": "H", "molecule_type": "protein", "sequence": "EVQLV", "msa": huge_msa},
            {"id": "A", "molecule_type": "protein", "sequence": "MKTAY"},
        )
    )
    with pytest.raises(ValueError, match="request bytes"):
        gateway.predict_complex(client_id="1.2.3.4", request=request)
