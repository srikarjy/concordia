from __future__ import annotations

import pytest

from concordia.colonies.live_run import run_live_colony


def test_run_live_colony_executes_a_fresh_colony_end_to_end(tmp_path) -> None:
    result = run_live_colony(tmp_path, population_size=2, generations=1, survivor_count=1)

    assert result["live"] is True
    assert result["scientific_use_allowed"] is False
    colony = result["colony"]
    assert colony["status"] in {"COMPLETED", "STAGNATED", "BUDGET_EXHAUSTED"}
    assert len(colony["members"]) >= 1
    assert colony["seed_member"]["status"] == "SEED"


def test_two_runs_produce_distinct_colony_ids(tmp_path) -> None:
    first = run_live_colony(tmp_path, population_size=2, generations=1)
    second = run_live_colony(tmp_path, population_size=2, generations=1)

    assert first["colony"]["spec"]["colony_id"] != second["colony"]["spec"]["colony_id"]


def test_rejects_out_of_bound_parameters(tmp_path) -> None:
    with pytest.raises(ValueError, match="population_size"):
        run_live_colony(tmp_path, population_size=99)
    with pytest.raises(ValueError, match="generations"):
        run_live_colony(tmp_path, generations=99)
    with pytest.raises(ValueError, match="survivor_count"):
        run_live_colony(tmp_path, population_size=2, survivor_count=5)
