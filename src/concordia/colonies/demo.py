"""Reproducible two-generation colony software demonstration."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from concordia.colonies.scheduler import ColonyScheduler
from concordia.colonies.schema import ColonySpec
from concordia.genomes import create_seed_genome


def run_colony_fixture_demo(state_root: str | Path) -> dict[str, Any]:
    scheduler = ColonyScheduler.local(state_root)
    task_digest = scheduler.artifacts.put_json(
        {
            "schema_version": 1,
            "question": "frozen genomic attribution audit fixture",
            "execution_mode": "software_fixture",
            "scientific_use_allowed": False,
        }
    )
    seed = create_seed_genome(hashlib.sha256(b"genomic-scientist-v3").hexdigest())
    spec = ColonySpec(
        colony_id="local-fixture-colony-v1",
        task_artifact_digest=task_digest,
        population_size=3,
        generations=2,
        survivor_count=1,
        max_total_members=6,
    )
    scheduler.create(spec, seed, idempotency_key="local-fixture-colony-v1")
    state = scheduler.run(spec.colony_id)
    return {
        "schema_version": 1,
        "colony_id": spec.colony_id,
        "status": state.status,
        "member_count": len(state.members),
        "generation_count": len(state.selections),
        "survivors": [selection.survivor_ids for selection in state.selections],
        "mutation_count": len(state.mutations),
        "event_count": state.event_count,
        "execution_mode": "deterministic_colony_fixture",
        "scientific_use_allowed": False,
    }
