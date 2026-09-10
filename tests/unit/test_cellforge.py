from __future__ import annotations

import socket
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from concordia.cellforge.contracts import (
    ExecutionRequest,
    ExecutionStatus,
    FilesystemPolicy,
    NetworkPolicy,
    ResourceBudget,
    SandboxPolicy,
    ToolCapability,
)
from concordia.cellforge.local import LocalExecutionAdapter
from concordia.cellforge.registry import (
    ExecutionContext,
    ToolDefinition,
    ToolRegistry,
    build_default_registry,
)
from concordia.cellforge.service import ToolExecutionService
from concordia.genomics.schema import GenomicSequence
from concordia.graph.schema import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphRelation,
)
from concordia.runtime.contracts import RunStatus
from concordia.runtime.service import CreateRunRequest, RunService
from concordia.scheduling.jobs import JobState
from concordia.storage.content import ContentAddressedStore


def fixture_request() -> CreateRunRequest:
    return CreateRunRequest(
        idempotency_key="cellforge-integration",
        sequence=GenomicSequence(
            sequence_id="fixture:cellforge",
            sequence="ACGT",
            assembly="GRCh38",
            region="chr1:0-4",
            strand="+",
        ),
        scan_position=1,
    )


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MessageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str


class PathInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str


def slow_handler(arguments: BaseModel, context: ExecutionContext) -> MessageOutput:
    del arguments, context
    print("partial-before-timeout", flush=True)
    time.sleep(5)
    return MessageOutput(message="late")


def oversized_handler(arguments: BaseModel, context: ExecutionContext) -> MessageOutput:
    del arguments, context
    return MessageOutput(message="x" * 1_000)


def path_handler(arguments: BaseModel, context: ExecutionContext) -> MessageOutput:
    del context
    request = PathInput.model_validate(arguments)
    return MessageOutput(message=request.path)


def network_handler(arguments: BaseModel, context: ExecutionContext) -> MessageOutput:
    del arguments, context
    socket.create_connection(("example.invalid", 80), timeout=0.1)
    return MessageOutput(message="unexpected")


def custom_definition(
    name: str,
    handler,
    *,
    input_model: type[BaseModel] = EmptyInput,
    capabilities: frozenset[ToolCapability] = frozenset(),
    network: NetworkPolicy = NetworkPolicy.DENY,
    path_arguments: tuple[str, ...] = (),
    filesystem: FilesystemPolicy = FilesystemPolicy.NONE,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0.0",
        input_model=input_model,
        output_model=MessageOutput,
        handler=handler,
        required_capabilities=capabilities,
        network=network,
        filesystem=filesystem,
        default_budget=ResourceBudget(),
        path_arguments=path_arguments,
    )


def policy(
    *tools: str,
    capabilities: frozenset[ToolCapability] = frozenset(),
    filesystem: FilesystemPolicy = FilesystemPolicy.NONE,
    readable_roots: tuple[str, ...] = (),
    network: NetworkPolicy = NetworkPolicy.DENY,
) -> SandboxPolicy:
    return SandboxPolicy(
        policy_version="test-policy-v1",
        allowed_tools=frozenset(tools),
        allowed_capabilities=capabilities,
        filesystem=filesystem,
        readable_roots=readable_roots,
        network=network,
    )


def request(
    tool: str,
    tool_policy: SandboxPolicy,
    *,
    arguments: dict[str, object] | None = None,
    budget: ResourceBudget | None = None,
    run_id: str = "run-1",
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id=f"request-{tool}",
        run_id=run_id,
        tool_name=tool,
        tool_version="1.0.0",
        arguments=arguments or {},
        budget=budget or ResourceBudget(),
        policy=tool_policy,
    )


def adapter(tmp_path: Path, registry: ToolRegistry) -> LocalExecutionAdapter:
    return LocalExecutionAdapter(
        registry,
        workspace_root=tmp_path / "workspace",
        artifact_root=tmp_path / "artifacts",
        temporary_root=tmp_path / "sandboxes",
    )


def test_undeclared_and_malformed_tools_are_rejected(tmp_path) -> None:
    registry = build_default_registry()
    local = adapter(tmp_path, registry)
    denied = local.execute(request("sequence.validate", policy()))
    assert denied.status is ExecutionStatus.REJECTED
    assert denied.error_code == "TOOL_NOT_ALLOWED"

    allowed = policy(
        "sequence.validate",
        capabilities=frozenset({ToolCapability.GENOMIC_COMPUTE}),
    )
    malformed = local.execute(
        request("sequence.validate", allowed, arguments={"sequence": "ACGT"})
    )
    assert malformed.status is ExecutionStatus.INVALID_ARGUMENTS


def test_timeout_terminates_sandbox_and_preserves_partial_output(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(custom_definition("test.slow", slow_handler))
    local = adapter(tmp_path, registry)

    result = local.execute(
        request(
            "test.slow",
            policy("test.slow"),
            budget=ResourceBudget(timeout_seconds=0.2, output_bytes=1_000),
        )
    )

    assert result.status is ExecutionStatus.TIMED_OUT
    assert "partial-before-timeout" in result.stdout
    assert result.error_code == "TIMEOUT"


def test_oversized_output_is_not_returned(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(custom_definition("test.large", oversized_handler))
    result = adapter(tmp_path, registry).execute(
        request(
            "test.large",
            policy("test.large"),
            budget=ResourceBudget(output_bytes=256),
        )
    )
    assert result.status is ExecutionStatus.OUTPUT_TOO_LARGE
    assert result.output == {}


def test_path_traversal_and_symlink_escape_are_rejected(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    safe = workspace / "safe"
    safe.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (safe / "escape").symlink_to(outside)
    (safe / "input.txt").write_text("allowed", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(
        custom_definition(
            "test.path",
            path_handler,
            input_model=PathInput,
            capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
            path_arguments=("path",),
            filesystem=FilesystemPolicy.READ_ONLY,
        )
    )
    local = adapter(tmp_path, registry)
    file_policy = policy(
        "test.path",
        capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
        filesystem=FilesystemPolicy.READ_ONLY,
        readable_roots=("safe",),
    )

    traversal = local.execute(
        request("test.path", file_policy, arguments={"path": "../outside.txt"})
    )
    symlink = local.execute(
        request("test.path", file_policy, arguments={"path": "safe/escape"})
    )
    absolute_root = local.execute(
        request(
            "test.path",
            policy(
                "test.path",
                capabilities=frozenset({ToolCapability.FILESYSTEM_READ}),
                filesystem=FilesystemPolicy.READ_ONLY,
                readable_roots=(str(tmp_path),),
            ),
            arguments={"path": "safe/input.txt"},
        )
    )
    accepted = local.execute(
        request("test.path", file_policy, arguments={"path": "safe/input.txt"})
    )
    assert traversal.status is ExecutionStatus.INVALID_ARGUMENTS
    assert symlink.status is ExecutionStatus.INVALID_ARGUMENTS
    assert absolute_root.status is ExecutionStatus.INVALID_ARGUMENTS
    assert accepted.status is ExecutionStatus.SUCCESS


def test_tool_budget_cannot_exceed_declared_limit(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(custom_definition("test.budget", oversized_handler))
    result = adapter(tmp_path, registry).execute(
        request(
            "test.budget",
            policy("test.budget"),
            budget=ResourceBudget(memory_megabytes=1_024),
        )
    )
    assert result.status is ExecutionStatus.REJECTED
    assert result.error_code == "BUDGET_EXCEEDS_TOOL_LIMIT"


def test_builtin_registry_exposes_complete_versioned_contracts() -> None:
    definitions = build_default_registry().definitions()
    assert {definition.name for definition in definitions} == {
        "artifact.verify",
        "evidence.verify",
        "graph.query",
        "lineage.backtrack",
        "sequence.validate",
        "variant.normalize",
        "xai.mutational_scan",
    }
    for definition in definitions:
        manifest = definition.manifest()
        assert manifest["version"] == "1.0.0"
        assert manifest["input_schema"]
        assert manifest["output_schema"]
        assert manifest["network_policy"] == NetworkPolicy.DENY


def test_network_policy_and_child_guard_both_fail_closed(tmp_path) -> None:
    requiring_network = ToolRegistry()
    requiring_network.register(
        custom_definition(
            "test.network-required",
            network_handler,
            capabilities=frozenset({ToolCapability.NETWORK}),
            network=NetworkPolicy.ALLOW,
        )
    )
    declared = adapter(tmp_path, requiring_network).execute(
        request(
            "test.network-required",
            policy(
                "test.network-required",
                capabilities=frozenset({ToolCapability.NETWORK}),
            ),
        )
    )
    assert declared.status is ExecutionStatus.REJECTED
    assert declared.error_code == "NETWORK_NOT_ALLOWED"

    guarded_registry = ToolRegistry()
    guarded_registry.register(custom_definition("test.network-guard", network_handler))
    guarded = adapter(tmp_path, guarded_registry).execute(
        request("test.network-guard", policy("test.network-guard"))
    )
    assert guarded.status is ExecutionStatus.FAILED
    assert guarded.error_code == "PermissionError"


def test_artifact_mismatch_is_reported_by_builtin_tool(tmp_path) -> None:
    store = ContentAddressedStore(tmp_path / "artifacts")
    digest = store.put_bytes(b"valid")
    store.path_for(digest).write_bytes(b"corrupt")
    result = adapter(tmp_path, build_default_registry()).execute(
        request(
            "artifact.verify",
            policy(
                "artifact.verify",
                capabilities=frozenset({ToolCapability.ARTIFACT_READ}),
            ),
            arguments={"digest": digest},
        )
    )
    assert result.status is ExecutionStatus.FAILED
    assert result.error_code == "ValueError"


def test_builtin_genomic_and_graph_tools_are_deterministic(tmp_path) -> None:
    registry = build_default_registry()
    local = adapter(tmp_path, registry)
    genomic_policy = policy(
        "sequence.validate",
        "variant.normalize",
        "xai.mutational_scan",
        capabilities=frozenset({ToolCapability.GENOMIC_COMPUTE}),
    )
    sequence = {
        "sequence_id": "fixture:tool",
        "sequence": "ACGT",
        "assembly": "GRCh38",
        "region": "chr1:0-4",
        "strand": "+",
    }
    validated = local.execute(
        request("sequence.validate", genomic_policy, arguments=sequence)
    )
    normalized = local.execute(
        request(
            "variant.normalize",
            genomic_policy,
            arguments={
                "sequence": sequence,
                "variant": {"position": 1, "reference": "C", "alternate": "T"},
            },
        )
    )
    scan = local.execute(
        request(
            "xai.mutational_scan",
            genomic_policy,
            arguments={"sequence": sequence, "position": 1},
        )
    )
    assert validated.status is ExecutionStatus.SUCCESS
    assert normalized.output["altered_sequence"]["sequence"] == "ATGT"
    assert len(scan.output["effects"]) == 3
    assert scan.output["scientific_use_allowed"] is False

    graph = EvidenceGraph(
        nodes=(
            GraphNode(node_id="claim", node_type=GraphNodeType.CLAIM, label="claim"),
            GraphNode(
                node_id="artifact",
                node_type=GraphNodeType.ARTIFACT,
                label="fixture",
                properties={"scientific_use_allowed": False},
            ),
        ),
        edges=(
            GraphEdge(
                edge_id="edge",
                source="claim",
                target="artifact",
                relation=GraphRelation.SUPPORTED_BY,
            ),
        ),
    )
    graph_digest = ContentAddressedStore(tmp_path / "artifacts").put_json(
        graph.model_dump(mode="json")
    )
    graph_policy = policy(
        "graph.query",
        "lineage.backtrack",
        "evidence.verify",
        capabilities=frozenset(
            {ToolCapability.ARTIFACT_READ, ToolCapability.GRAPH_READ}
        ),
    )
    graph_arguments = {
        "graph_digest": graph_digest,
        "source_node_id": "claim",
        "target_node_id": "artifact",
    }
    query = local.execute(request("graph.query", graph_policy, arguments=graph_arguments))
    verified = local.execute(
        request("evidence.verify", graph_policy, arguments=graph_arguments)
    )
    assert query.output["path"] == ["claim", "artifact"]
    assert verified.output["verification"]["status"] == "UNVERIFIABLE"


def test_tool_execution_is_persisted_in_events_artifacts_and_graph(tmp_path) -> None:
    runs = RunService.local(tmp_path / "run-state")
    scheduled = runs.create_scheduled(fixture_request())
    lease = runs.jobs.claim("tool-worker", run_id=scheduled.spec.run_id)
    assert lease is not None
    runs.transition(scheduled.spec.run_id, RunStatus.EXECUTING)
    local = LocalExecutionAdapter(
        build_default_registry(),
        workspace_root=tmp_path,
        artifact_root=runs.artifacts.root,
        temporary_root=tmp_path / "sandboxes",
    )
    service = ToolExecutionService(runs, local)
    tool_policy = policy(
        "sequence.validate",
        capabilities=frozenset({ToolCapability.GENOMIC_COMPUTE}),
    )

    result = service.execute(
        request(
            "sequence.validate",
            tool_policy,
            run_id=scheduled.spec.run_id,
            arguments={
                "sequence_id": "fixture:integrated",
                "sequence": "ACGT",
                "assembly": "GRCh38",
                "region": "chr1:0-4",
                "strand": "+",
            },
        )
    )

    assert result.status is ExecutionStatus.SUCCESS
    events = runs.ledger.all_events(scheduled.spec.run_id)
    assert [event.event_type for event in events[-2:]] == [
        "TOOL_EXECUTION_STARTED",
        "TOOL_EXECUTION_FINISHED",
    ]
    references = events[-1].payload["artifacts"]
    assert len(references) == 2
    provenance_reference = next(
        value for value in references if value["producing_tool"].startswith("cellforge")
    )
    provenance = EvidenceGraph.model_validate_json(
        runs.artifacts.get_bytes(provenance_reference["digest"])
    )
    assert {node.node_type for node in provenance.nodes} == {
        GraphNodeType.TOOL_RUN,
        GraphNodeType.ARTIFACT,
    }
    assert runs.jobs.get(scheduled.spec.run_id).state is JobState.LEASED
