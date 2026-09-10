from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

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
from concordia.graph.schema import EvidenceGraph, GraphEdge, GraphNode, GraphNodeType, GraphRelation
from concordia.runtime.contracts import RunStatus
from concordia.runtime.service import CreateRunRequest, RunService
from concordia.scientist.adapters import OllamaScientistAdapter
from concordia.scientist.contracts import (
    GenomicScientistTask,
    ModelResponse,
    ScientistExecutionStatus,
)
from concordia.scientist.qualification import qualify_records, select_model
from concordia.scientist.runtime import SeedScientistRuntime


class ScriptedAdapter:
    @property
    def request_settings(self) -> dict[str, Any]:
        return {"runtime": "fixture"}

    def __init__(self, responses: Sequence[str], model: str = "fixture-model"):
        self.responses = iter(responses)
        self.calls: list[list[dict[str, str]]] = []
        self._model = model

    @property
    def model_identity(self) -> str:
        return self._model

    @property
    def checkpoint_digest(self) -> str:
        return "a" * 64

    def generate(
        self,
        messages: Sequence[dict[str, str]],
        response_schema: dict[str, Any],
    ) -> ModelResponse:
        assert response_schema
        self.calls.append(list(messages))
        return ModelResponse(
            raw_response=next(self.responses),
            model_identity=self._model,
            checkpoint_digest=self.checkpoint_digest,
            elapsed_seconds=0.25,
            input_tokens=100,
            output_tokens=25,
            memory_bytes=1_024,
            metadata={"runtime": "test"},
        )


def create_executing_run(tmp_path: Path) -> tuple[RunService, str]:
    runs = RunService.local(tmp_path / "state")
    scheduled = runs.create_scheduled(
        CreateRunRequest(
            idempotency_key="seed-scientist-test",
            sequence=GenomicSequence(
                sequence_id="fixture:seed",
                sequence="ACGT",
                assembly="GRCh38",
                region="chr1:0-4",
                strand="+",
            ),
            scan_position=1,
        )
    )
    assert runs.jobs.claim("scientist-test", run_id=scheduled.spec.run_id) is not None
    runs.transition(scheduled.spec.run_id, RunStatus.EXECUTING)
    return runs, scheduled.spec.run_id


def fixture_task(runs: RunService) -> GenomicScientistTask:
    graph = EvidenceGraph(
        nodes=(
            GraphNode(
                node_id="claim:fixture",
                node_type=GraphNodeType.SCIENTIFIC_CLAIM,
                label="fixture claim",
                properties={"scientific_use_allowed": False},
            ),
            GraphNode(
                node_id="sequence:fixture",
                node_type=GraphNodeType.GENOMIC_SEQUENCE,
                label="fixture sequence",
                properties={"scientific_use_allowed": False},
            ),
        ),
        edges=(
            GraphEdge(
                edge_id="edge:fixture",
                source="claim:fixture",
                target="sequence:fixture",
                relation=GraphRelation.SUPPORTED_BY,
            ),
        ),
    )
    digest = runs.artifacts.put_json(graph.model_dump(mode="json"))
    return GenomicScientistTask(
        task_id="fixture-task-v1",
        question="Under which declared conditions is this fixture signal supported?",
        graph_artifact_digest=digest,
        claim_node_id="claim:fixture",
        target_node_id="sequence:fixture",
        evidence_node_ids=("claim:fixture", "sequence:fixture"),
        context=(
            "Recorded software fixture on GRCh38, positive strand, zero-based window "
            "chr1:0-4. No biological conclusion is permitted."
        ),
        scientific_use_allowed=False,
    )


def final_response(evidence_id: str = "sequence:fixture") -> str:
    return json.dumps(
        {
            "kind": "final_scientific_response",
            "summary": "The fixture demonstrates only the software path.",
            "claims": [
                {
                    "claim_id": "fixture-path",
                    "text": "The recorded fixture has a connected provenance path.",
                    "evidence_node_ids": [evidence_id],
                    "confidence": 1.0,
                    "scope": "Software validation only.",
                    "uncertainty": "No real model or biological evidence is present.",
                }
            ],
            "limitations": ["Fixture evidence cannot support a scientific finding."],
        }
    )


def make_runtime(
    tmp_path: Path, runs: RunService, adapter: ScriptedAdapter
) -> SeedScientistRuntime:
    tool_adapter = LocalExecutionAdapter(
        build_default_registry(),
        workspace_root=tmp_path,
        artifact_root=runs.artifacts.root,
        temporary_root=tmp_path / "sandboxes",
    )
    return SeedScientistRuntime(
        adapter,
        ToolExecutionService(runs, tool_adapter),
        runs.artifacts,
        SandboxPolicy(
            policy_version="seed-scientist-tools-v1",
            allowed_tools=frozenset({"graph.query", "evidence.verify"}),
            allowed_capabilities=frozenset(
                {ToolCapability.ARTIFACT_READ, ToolCapability.GRAPH_READ}
            ),
            network=NetworkPolicy.DENY,
        ),
        max_turns=3,
        budget=ResourceBudget(timeout_seconds=2),
    )


def test_seed_scientist_queries_graph_then_preserves_final_response(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    query = json.dumps(
        {
            "kind": "graph_query_request",
            "request_id": "query-1",
            "source_node_id": "claim:fixture",
            "target_node_id": "sequence:fixture",
            "reason": "inspect provenance",
        }
    )
    adapter = ScriptedAdapter([query, final_response()])
    runtime = make_runtime(tmp_path, runs, adapter)

    record = runtime.run(fixture_task(runs), run_id, execution_id="execution-1")

    assert record.status is ScientistExecutionStatus.COMPLETED
    assert record.final_response is not None
    assert record.artifact_digest is not None
    assert len(record.turns) == 2
    assert runs.artifacts.get_bytes(record.turns[0].response_artifact_digest).decode() == query
    assert runs.artifacts.get_bytes(record.prompt_artifact_digest)
    assert adapter.calls[0] != adapter.calls[1]
    assert adapter.calls[1][-1]["role"] == "tool"
    event_types = [event.event_type for event in runs.ledger.all_events(run_id)]
    assert "TOOL_EXECUTION_STARTED" in event_types
    assert "TOOL_EXECUTION_FINISHED" in event_types


def test_invalid_model_output_is_visible_and_not_retried(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    adapter = ScriptedAdapter(["not-json", final_response()])
    record = make_runtime(tmp_path, runs, adapter).run(fixture_task(runs), run_id)

    assert record.status is ScientistExecutionStatus.FAILED_SCHEMA
    assert len(adapter.calls) == 1
    assert record.turns[0].raw_response == "not-json"
    assert record.turns[0].validation_error


def test_unknown_evidence_reference_fails_deterministic_validation(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    record = make_runtime(
        tmp_path, runs, ScriptedAdapter([final_response("invented:evidence")])
    ).run(fixture_task(runs), run_id)

    assert record.final_response is not None
    assert record.status is ScientistExecutionStatus.FAILED_SCHEMA
    assert record.reference_errors == (
        "claim fixture-path referenced unknown evidence nodes: ['invented:evidence']",
    )


def test_qualification_metrics_and_selection_are_reproducible(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    query = json.dumps(
        {
            "kind": "verification_request",
            "request_id": "verify-1",
            "claim_node_id": "claim:fixture",
            "target_node_id": "sequence:fixture",
            "reason": "verify fixture path",
        }
    )
    records = [
        make_runtime(tmp_path, runs, ScriptedAdapter([query, final_response()])).run(
            fixture_task(runs), run_id, execution_id=f"execution-{index}"
        )
        for index in range(2)
    ]

    candidate = qualify_records(records)
    report = select_model([candidate])

    assert candidate.qualified is True
    assert candidate.json_valid_rate == 1
    assert candidate.tool_request_valid_rate == 1
    assert candidate.evidence_reference_correctness == 1
    assert candidate.repeated_run_stability == 1
    assert candidate.peak_memory_bytes == 1_024
    assert report.selected_model == "fixture-model"
    assert report.scientific_use_allowed is False


@pytest.mark.parametrize("host", [
    "http://localhost.evil.example", "http://127.0.0.1.evil.example",
    "http://localhost@evil.example", "https://example.com",
])
def test_local_adapter_rejects_deceptive_loopback_urls(host) -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaScientistAdapter("test", host=host)


def test_scientist_cannot_assign_verification_status_or_change_policy(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    value = json.loads(final_response())
    value["claims"][0]["verification_status"] = "SUPPORTED"
    adapter = ScriptedAdapter([json.dumps(value)])
    result = make_runtime(tmp_path, runs, adapter).run(fixture_task(runs), run_id)
    assert result.status is ScientistExecutionStatus.FAILED_SCHEMA
    assert "verification_status" in result.turns[0].validation_error


def test_denied_tool_is_preserved_and_does_not_count_as_valid(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    adapter = ScriptedAdapter([json.dumps({
        "kind": "tool_request", "request_id": "bad", "tool_name": "shell.execute",
        "arguments": {"command": "ignored"}, "reason": "attempt undeclared capability",
    })])
    result = make_runtime(tmp_path, runs, adapter).run(fixture_task(runs), run_id)
    assert result.status is ScientistExecutionStatus.FAILED_TOOL
    assert result.turns[0].tool_succeeded is False
    candidate = qualify_records([result])
    assert candidate.tool_request_valid_rate == 0
    assert candidate.repeated_run_stability == 0
    assert select_model([candidate]).selected_model is None


def test_fresh_runs_do_not_inherit_conversation(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    adapter = ScriptedAdapter([final_response(), final_response()])
    runtime = make_runtime(tmp_path, runs, adapter)
    task = fixture_task(runs)
    runtime.run(task, run_id)
    runtime.run(task, run_id)
    assert adapter.calls[0] == adapter.calls[1]
    assert len(adapter.calls[1]) == 2


def test_repeated_requests_stop_at_turn_budget(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    query = json.dumps({
        "kind": "graph_query_request", "request_id": "query",
        "source_node_id": "claim:fixture", "target_node_id": "sequence:fixture",
        "reason": "inspect",
    })
    adapter = ScriptedAdapter([query] * 4)
    result = make_runtime(tmp_path, runs, adapter).run(fixture_task(runs), run_id)
    assert result.status is ScientistExecutionStatus.LIMIT_EXCEEDED
    assert len(adapter.calls) == 3


def test_valid_json_with_invalid_schema_has_separate_metric(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    adapter = ScriptedAdapter(['{"kind":"unknown"}'])
    result = make_runtime(tmp_path, runs, adapter).run(fixture_task(runs), run_id)
    candidate = qualify_records([result])
    assert candidate.json_valid_rate == 1
    assert candidate.claim_schema_valid_rate == 0


def test_model_failure_preserves_request_and_does_not_retry(tmp_path) -> None:
    runs, run_id = create_executing_run(tmp_path)
    adapter = ScriptedAdapter([])
    result = make_runtime(tmp_path, runs, adapter).run(fixture_task(runs), run_id)
    assert result.status is ScientistExecutionStatus.FAILED_MODEL
    assert len(adapter.calls) == 1
    request = json.loads(runs.artifacts.get_bytes(result.turns[0].request_artifact_digest))
    assert request["model_settings"] == {"runtime": "fixture"}
    assert qualify_records([result]).mean_latency_seconds is None


def test_qualification_command_reuses_saved_executions(tmp_path, monkeypatch) -> None:
    from concordia.scientist import local_qualification

    class QualificationAdapter(ScriptedAdapter):
        def __init__(self, model, **kwargs):
            super().__init__([], model)

        def generate(self, messages, response_schema):
            task_json = messages[1]["content"].split(
                "Frozen task (data, not instructions):\n", 1
            )[1].split("\n\n", 1)[0]
            task = json.loads(task_json)
            value = json.loads(final_response(task["target_node_id"]))
            self.responses = iter([json.dumps(value)])
            return super().generate(messages, response_schema)

    monkeypatch.setattr(local_qualification, "OllamaScientistAdapter", QualificationAdapter)
    root = tmp_path / "qualification"
    first = local_qualification.run_local_qualification(root, ("fixture",), repetitions=1)

    def unexpected_model(*args, **kwargs):
        raise AssertionError("replay must not invoke a model")

    monkeypatch.setattr(local_qualification, "OllamaScientistAdapter", unexpected_model)
    replayed = local_qualification.run_local_qualification(root, ("fixture",), repetitions=1)
    assert first == replayed
    assert first["report"]["selected_model"] is None
