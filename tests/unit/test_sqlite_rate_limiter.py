from __future__ import annotations

import pytest

from concordia.genomics.rate_limiting import RateLimitExceededError, SqliteRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now


def test_per_client_limit_is_enforced(tmp_path) -> None:
    limiter = SqliteRateLimiter(
        database_path=tmp_path / "rl.sqlite3", per_client_limit=2, clock=FakeClock()
    )
    limiter.check_and_record("a")
    limiter.check_and_record("a")
    with pytest.raises(RateLimitExceededError):
        limiter.check_and_record("a")

    limiter.check_and_record("b")  # different client unaffected


def test_global_daily_limit_is_enforced(tmp_path) -> None:
    limiter = SqliteRateLimiter(
        database_path=tmp_path / "rl.sqlite3",
        per_client_limit=10,
        global_daily_limit=2,
        clock=FakeClock(),
    )
    limiter.check_and_record("a")
    limiter.check_and_record("b")
    with pytest.raises(RateLimitExceededError):
        limiter.check_and_record("c")


def test_window_resets_after_elapsed_time(tmp_path) -> None:
    clock = FakeClock()
    limiter = SqliteRateLimiter(
        database_path=tmp_path / "rl.sqlite3",
        per_client_limit=1,
        per_client_window_seconds=60,
        clock=clock,
    )
    limiter.check_and_record("a")
    with pytest.raises(RateLimitExceededError):
        limiter.check_and_record("a")
    clock.now += 61
    limiter.check_and_record("a")


def test_rejects_invalid_table_name(tmp_path) -> None:
    with pytest.raises(ValueError, match="identifier"):
        SqliteRateLimiter(database_path=tmp_path / "rl.sqlite3", table_name="bad; drop table")
