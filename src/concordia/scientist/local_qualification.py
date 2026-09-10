"""Local infrastructure orchestration for genomic scientist qualification."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from concordia.cellforge.contracts import (
    NetworkPolicy,
    ResourceBudget,
    SandboxPolicy,
    ToolCapability,
)
from concordia.cellforge.local import LocalExecutionAdapter
from concordia.cellforge.registry import build_default_registry
from concordia.cellforge.service import ToolExecutionService
from concordia.genomics.schema import GenomicSequence
from concordia.graph.schema import EvidenceGraph
from concordia.runtime.contracts import ArtifactReference, RunStatus
from concordia.runtime.service import CreateRunRequest, RunService
from concordia.scheduling.jobs import JobState
from concordia.scientist.adapters import OllamaScientistAdapter
from concordia.scientist.contracts import (
    GenomicScientistTask,
    ScientistExecutionRecord,
    ScientistExecutionStatus,
)
from concordia.scientist.qualification import (
    QualificationCriteria,
    qualify_records,
    select_model,
)
from concordia.scientist.runtime import SeedScientistRuntime


def run_local_qualification(
    state_root: str | Path,
    models: tuple[str, ...],
    *,
    repetitions: int = 2,
    seed: int = 1729,
) -> dict[str, Any]:
    if not models:
        raise ValueError("at least one candidate model is required")
    if repetitions < 1 or repetitions > 10:
        raise ValueError("repetitions must be between 1 and 10")
    root = Path(state_root)
    runs = RunService.local(root)
    task = _qualification_task(runs)
    criteria = QualificationCriteria()
    protocol_digest = runs.artifacts.put_json({
        "criteria": criteria.model_dump(mode="json"),
        "models": models, "repetitions": repetitions, "seed": seed,
        "transport_version": "ollama-json-v1",
        "task": task.model_dump(mode="json"),
    })
    qualifications = []
    for model in models:
        records = tuple(
            _run_candidate(runs, root, task, model, repetition, seed)
            for repetition in range(repetitions)
        )
        qualifications.append(qualify_records(records, criteria))
    report = select_model(qualifications, criteria)
    report_digest = runs.artifacts.put_json(report.model_dump(mode="json"))
    manifest = {
        "schema_version": 1,
        "protocol_artifact_digest": protocol_digest,
        "report_artifact_digest": report_digest,
        "report": report.model_dump(mode="json"),
    }
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / "qualification.json.tmp"
    target = root / "qualification.json"
    temporary.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return manifest


def _qualification_task(runs: RunService) -> GenomicScientistTask:
    evidence = runs.create_and_execute(
        CreateRunRequest(
            idempotency_key="scientist-qualification-evidence-v1",
            protocol_version="scientist-qualification-fixture-v1",
            sequence=GenomicSequence(
                sequence_id="fixture:scientist-qualification",
                sequence="ACGTTGCAACGT",
                assembly="GRCh38",
                region="chr1:0-12",
                strand="+",
            ),
            scan_position=4,
        )
    )
    reference = next(
        item
        for item in runs.artifact_references(evidence.spec.run_id)
        if item.producing_tool == "graph.fixture_builder"
    )
    graph = EvidenceGraph.model_validate_json(runs.artifacts.get_bytes(reference.digest))
    return GenomicScientistTask(
        task_id="local-genomic-qualification-v1",
        question=(
            "Under which declared conditions does the recorded attribution fixture have a "
            "complete provenance path?"
        ),
        graph_artifact_digest=reference.digest,
        claim_node_id="claim:fixture-1",
        target_node_id=f"sequence:{evidence.spec.task.sequence_artifact_id}",
        evidence_node_ids=tuple(sorted(node.node_id for node in graph.nodes)),
        context=(
            "Software-only recorded fixture for GRCh38, positive strand, zero-based window "
            "chr1:0-12. It contains counterfactual model-behavior evidence but no real Evo2 "
            "execution or biological validation. It cannot support a scientific finding."
        ),
        scientific_use_allowed=False,
    )


def _run_candidate(
    runs: RunService,
    root: Path,
    task: GenomicScientistTask,
    model: str,
    repetition: int,
    seed: int,
) -> ScientistExecutionRecord:
    safe_model = model.replace("/", "_")
    scheduled = runs.create_scheduled(
        CreateRunRequest(
            idempotency_key=f"scientist-qualification:{safe_model}:{repetition}:{seed}",
            protocol_version="genomic-scientist-qualification-v1",
            policy_version="seed-scientist-tools-v1",
            sequence=GenomicSequence(
                sequence_id="fixture:scientist-qualification",
                sequence="ACGTTGCAACGT",
                assembly="GRCh38",
                region="chr1:0-12",
                strand="+",
            ),
            scan_position=4,
        )
    )
    if scheduled.current_status is not RunStatus.SCHEDULED:
        for event in runs.ledger.all_events(scheduled.spec.run_id):
            if event.event_type == "SCIENTIST_EXECUTION_FINISHED":
                digest = event.payload["artifacts"][0]["digest"]
                saved = ScientistExecutionRecord.model_validate_json(
                    runs.artifacts.get_bytes(digest)
                )
                return saved.model_copy(update={"artifact_digest": digest})
        raise ValueError("partial qualification requires inspection; inference is not retried")
    lease = runs.jobs.claim(
        f"scientist-{safe_model}-{repetition}", run_id=scheduled.spec.run_id,
        lease_seconds=1800,
    )
    if lease is None:
        raise RuntimeError("qualification run could not claim its local lease")
    runs.transition(scheduled.spec.run_id, RunStatus.EXECUTING)
    policy = SandboxPolicy(
        policy_version="seed-scientist-tools-v1",
        allowed_tools=frozenset({"graph.query", "evidence.verify"}),
        allowed_capabilities=frozenset(
            {ToolCapability.ARTIFACT_READ, ToolCapability.GRAPH_READ}
        ),
        network=NetworkPolicy.DENY,
    )
    local_tools = LocalExecutionAdapter(
        build_default_registry(),
        workspace_root=Path.cwd(),
        artifact_root=runs.artifacts.root,
        temporary_root=root / "sandboxes",
    )
    runtime = SeedScientistRuntime(
        OllamaScientistAdapter(model, temperature=0, seed=seed),
        ToolExecutionService(runs, local_tools),
        runs.artifacts,
        policy,
        max_turns=4,
        budget=ResourceBudget(timeout_seconds=10),
    )
    record = runtime.run(task, scheduled.spec.run_id)
    _record_execution_event(runs, record)
    if record.status is ScientistExecutionStatus.COMPLETED:
        for status in (
            RunStatus.CLAIM_VALIDATION,
            RunStatus.BACKTRACKING,
            RunStatus.EVALUATING,
            RunStatus.REPORTING,
            RunStatus.COMPLETED,
        ):
            runs.transition(scheduled.spec.run_id, status)
        runs.jobs.finish(lease, JobState.DONE)
    else:
        failure = {
            ScientistExecutionStatus.FAILED_MODEL: RunStatus.FAILED_MODEL,
            ScientistExecutionStatus.FAILED_SCHEMA: RunStatus.FAILED_SCHEMA,
            ScientistExecutionStatus.FAILED_TOOL: RunStatus.FAILED_TOOL,
            ScientistExecutionStatus.LIMIT_EXCEEDED: RunStatus.FAILED_MODEL,
        }[record.status]
        runs.transition(
            scheduled.spec.run_id,
            failure,
            reason=record.terminal_reason,
        )
        runs.jobs.finish(lease, JobState.FAILED)
    return record


def _record_execution_event(runs: RunService, record: ScientistExecutionRecord) -> None:
    if record.artifact_digest is None:
        raise ValueError("scientist execution record was not persisted")
    event_id = str(uuid.uuid4())
    reference = ArtifactReference(
        digest=record.artifact_digest,
        media_type="application/json",
        byte_size=len(runs.artifacts.get_bytes(record.artifact_digest)),
        schema_version=1,
        producing_event=event_id,
        producing_tool="scientist.seed_runtime@1.0.0",
        scientific_use_allowed=False,
    )
    current = runs.get_run(record.run_id)
    runs.ledger.append(
        record.run_id,
        "SCIENTIST_EXECUTION_FINISHED",
        {
            "execution_id": record.execution_id,
            "status": record.status,
            "artifacts": [reference.model_dump(mode="json")],
        },
        expected_sequence=current.last_sequence_number,
        event_id=event_id,
    )
