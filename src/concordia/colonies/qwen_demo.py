"""Measured local-Qwen colony run over a frozen non-scientific evidence task."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from concordia.colonies.executor import LocalScientistExecutorFactory
from concordia.colonies.scheduler import ColonyScheduler
from concordia.colonies.schema import ColonySpec, MemberStatus
from concordia.colonies.store import SQLiteColonyLedger
from concordia.genomes import create_seed_genome
from concordia.runtime.service import RunService
from concordia.scientist.local_qualification import _qualification_task
from concordia.storage.content import ContentAddressedStore


def run_qwen_colony_demo(
    state_root: str | Path,
    *,
    model: str = "qwen3:1.7b",
    seed: int = 1729,
) -> dict[str, Any]:
    """Execute three isolated model sessions; outputs remain software evidence only."""
    root = Path(state_root)
    evidence_runs = RunService.local(root / "evidence")
    source_task = _qualification_task(evidence_runs)
    colony_root = root / "colony"
    artifacts = ContentAddressedStore(colony_root / "artifacts")
    graph_bytes = evidence_runs.artifacts.get_bytes(source_task.graph_artifact_digest)
    graph_digest = artifacts.put_bytes(graph_bytes)
    task = source_task.model_copy(
        update={
            "task_id": "qwen-colony-software-audit-v1",
            "graph_artifact_digest": graph_digest,
        }
    )
    task_digest = artifacts.put_json(task.model_dump(mode="json"))
    factory = LocalScientistExecutorFactory(
        model,
        artifacts,
        Path.cwd(),
        colony_root / "sandboxes",
        seed=seed,
    )
    scheduler = ColonyScheduler(
        SQLiteColonyLedger(colony_root / "colony.sqlite3"),
        artifacts,
        factory,
    )
    seed_genome = create_seed_genome(
        hashlib.sha256(b"genomic-scientist-v3").hexdigest()
    )
    safe_model = model.replace("/", "_").replace(":", "_")
    spec = ColonySpec(
        colony_id=f"local-qwen-colony-{safe_model}-v1",
        task_artifact_digest=task_digest,
        population_size=3,
        generations=1,
        survivor_count=1,
        max_total_members=3,
        max_concurrency=1,
        random_seed=seed,
    )
    scheduler.create(
        spec,
        seed_genome,
        idempotency_key=f"{spec.colony_id}:{task_digest}:{seed}",
    )
    state = scheduler.run(spec.colony_id)
    return {
        "schema_version": 1,
        "colony_id": spec.colony_id,
        "status": state.status,
        "model": model,
        "task_artifact_digest": task_digest,
        "member_count": len(state.members),
        "completed_members": sum(member.output_digest is not None for member in state.members),
        "failed_members": sum(
            member.status is MemberStatus.FAILED for member in state.members
        ),
        "extinct_members": sum(
            member.status is MemberStatus.EXTINCT for member in state.members
        ),
        "survivors": [selection.survivor_ids for selection in state.selections],
        "fitness": {
            member.member_id: member.fitness.model_dump(mode="json")
            for member in state.members
            if member.fitness is not None
        },
        "execution_mode": "local_scientist",
        "scientific_use_allowed": False,
        "limitation": (
            "Selection measures protocol behavior on a fixture task; it is not a "
            "scientific result or model-truth judgment."
        ),
    }
