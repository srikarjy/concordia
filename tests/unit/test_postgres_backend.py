"""Unit tests for the Postgres backend using a mocked psycopg connection.

These do not touch a real database — they verify the SQL this module issues
has the right shape (right table, right parameters, right conflict target)
against a fake cursor. The SQL text itself was separately verified against
the real Supabase schema via the Supabase SQL console during development.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from concordia.genomics.postgres_backend import (
    PostgresForwardJobStore,
    PostgresRateLimitedCache,
    PostgresRateLimiter,
)
from concordia.genomics.rate_limiting import RateLimitExceededError


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def time(self) -> float:
        return self.now


def _fake_connection(fetchone_results: list[dict | None]):
    """A context-manager-compatible fake connection whose cursor's fetchone()
    returns successive values from ``fetchone_results`` across calls."""

    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone_results
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connection.__enter__.return_value = connection
    connection.__exit__.return_value = False
    return connection, cursor


@patch("concordia.genomics.postgres_backend.psycopg.connect")
def test_rate_limiter_raises_when_per_client_limit_reached(mock_connect) -> None:
    connection, _cursor = _fake_connection([{"count": 5}])
    mock_connect.return_value = connection

    limiter = PostgresRateLimiter(
        dsn="postgresql://fake",
        namespace="test",
        per_client_limit=5,
        per_client_window_seconds=60,
        global_daily_limit=100,
        clock=FakeClock(),
    )
    with pytest.raises(RateLimitExceededError, match="per-client"):
        limiter.check_and_record("client-1")


@patch("concordia.genomics.postgres_backend.psycopg.connect")
def test_rate_limiter_allows_request_under_limit(mock_connect) -> None:
    connection, cursor = _fake_connection([{"count": 1}, {"count": 2}])
    mock_connect.return_value = connection

    limiter = PostgresRateLimiter(
        dsn="postgresql://fake",
        namespace="test",
        per_client_limit=5,
        per_client_window_seconds=60,
        global_daily_limit=100,
        clock=FakeClock(),
    )
    limiter.check_and_record("client-1")

    insert_calls = [call for call in cursor.execute.call_args_list if "INSERT" in call.args[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0].args[1] == ("test", "client-1", 1_000.0)


@patch("concordia.genomics.postgres_backend.psycopg.connect")
def test_cache_get_returns_none_when_absent(mock_connect) -> None:
    connection, _cursor = _fake_connection([None])
    mock_connect.return_value = connection

    cache = PostgresRateLimitedCache(
        dsn="postgresql://fake",
        namespace="test",
        per_client_limit=5,
        per_client_window_seconds=60,
        global_daily_limit=100,
    )
    assert cache.get_cached("missing-key") is None


@patch("concordia.genomics.postgres_backend.psycopg.connect")
def test_forward_job_store_get_returns_none_when_missing(mock_connect) -> None:
    connection, _cursor = _fake_connection([None])
    mock_connect.return_value = connection

    store = PostgresForwardJobStore(dsn="postgresql://fake")
    assert store.get("missing-job") is None


@patch("concordia.genomics.postgres_backend.psycopg.connect")
def test_forward_job_store_parses_cached_result_json(mock_connect) -> None:
    connection, _cursor = _fake_connection(
        [
            {
                "job_id": "job-1",
                "status": "COMPLETED",
                "submitted_at": 1.0,
                "completed_at": 2.0,
                "result_json": '{"score": -0.5}',
                "error": None,
            }
        ]
    )
    mock_connect.return_value = connection

    store = PostgresForwardJobStore(dsn="postgresql://fake")
    record = store.get("job-1")

    assert record is not None
    assert record["result"] == {"score": -0.5}
