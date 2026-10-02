"""Run one fresh, real colony simulation synchronously for an interactive caller.

Unlike the saved workspace demonstration (one fixed colony replayed from
disk), this executes ``ColonyScheduler`` end to end on each call: a new
digital genome, new allowlisted mutations, a new deterministic fitness
evaluation, and new survivor selection. It uses the deterministic fixture
executor (no LLM, no GPU) so it completes in well under a second and needs
no extra infrastructure — the scientific-quality fitness components remain
zero because the task is a frozen software fixture, exactly as in every
other colony demonstration in this project. This is a real execution of
real scheduling code, not a replay, but it is still not scientific evidence.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from concordia.colonies.scheduler import ColonyScheduler
from concordia.colonies.schema import ColonySpec
from concordia.genomes import create_seed_genome

MAX_POPULATION_SIZE = 6
MAX_GENERATIONS = 3
MAX_TOTAL_MEMBERS = 18


def run_live_colony(
    state_root: str | Path,
    *,
    population_size: int = 3,
    generations: int = 2,
    survivor_count: int = 1,
) -> dict[str, Any]:
    if not 1 <= population_size <= MAX_POPULATION_SIZE:
        raise ValueError(f"population_size must be 1-{MAX_POPULATION_SIZE}")
    if not 1 <= generations <= MAX_GENERATIONS:
        raise ValueError(f"generations must be 1-{MAX_GENERATIONS}")
    if not 1 <= survivor_count <= population_size:
        raise ValueError("survivor_count must be between 1 and population_size")

    scheduler = ColonyScheduler.local(Path(state_root) / "live_colonies")
    colony_id = f"live-{uuid.uuid4().hex}"
    task_digest = scheduler.artifacts.put_json(
        {
            "schema_version": 1,
            "question": "interactive colony simulation fixture",
            "execution_mode": "software_fixture",
            "scientific_use_allowed": False,
        }
    )
    seed = create_seed_genome(hashlib.sha256(colony_id.encode("utf-8")).hexdigest())
    spec = ColonySpec(
        colony_id=colony_id,
        task_artifact_digest=task_digest,
        population_size=population_size,
        generations=generations,
        survivor_count=survivor_count,
        max_total_members=min(MAX_TOTAL_MEMBERS, population_size * generations * 2),
    )
    scheduler.create(spec, seed, idempotency_key=colony_id)
    state = scheduler.run(colony_id)
    return {
        "schema_version": 1,
        "execution_mode": "deterministic_colony_fixture",
        "scientific_use_allowed": False,
        "live": True,
        "colony": state.model_dump(mode="json"),
    }
