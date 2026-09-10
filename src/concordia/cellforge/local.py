"""Process-isolated local execution adapter for trusted built-in tools."""

from __future__ import annotations

import contextlib
import json
import multiprocessing
import os
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from concordia.cellforge.contracts import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    FilesystemPolicy,
    NetworkPolicy,
    SandboxPolicy,
)
from concordia.cellforge.registry import ExecutionContext, ToolDefinition, ToolRegistry


def _deny_network(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise PermissionError("network access is denied by sandbox policy")


def _apply_resource_limits(memory_megabytes: int, timeout_seconds: float) -> None:
    try:
        import resource
    except ImportError:
        return
    cpu_seconds = max(1, int(timeout_seconds) + 1)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    if sys.platform.startswith("linux"):
        memory_bytes = memory_megabytes * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _child_execute(
    definition: ToolDefinition,
    arguments: dict[str, Any],
    context: ExecutionContext,
    network: NetworkPolicy,
    memory_megabytes: int,
    timeout_seconds: float,
    output_bytes: int,
    send_connection: Any,
    ready_event: Any,
    stdout_path: str,
    stderr_path: str,
) -> None:
    os.chdir(context.sandbox_root)
    _apply_resource_limits(memory_megabytes, timeout_seconds)
    if network is NetworkPolicy.DENY:
        socket.socket = _deny_network  # type: ignore[misc,assignment]
        socket.create_connection = _deny_network  # type: ignore[assignment]
    envelope: dict[str, Any]
    with (
        Path(stdout_path).open("w", encoding="utf-8") as stdout_handle,
        Path(stderr_path).open("w", encoding="utf-8") as stderr_handle,
        contextlib.redirect_stdout(stdout_handle),
        contextlib.redirect_stderr(stderr_handle),
    ):
        ready_event.set()
        try:
            validated_input = definition.input_model.model_validate(arguments)
            output = definition.handler(validated_input, context)
            validated_output = definition.output_model.model_validate(output)
            serialized_output = validated_output.model_dump(mode="json")
            encoded = json.dumps(
                serialized_output, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if len(encoded) > output_bytes:
                envelope = {
                    "status": ExecutionStatus.OUTPUT_TOO_LARGE,
                    "error_code": "OUTPUT_LIMIT_EXCEEDED",
                    "error_message": "tool output exceeded its declared byte limit",
                }
            else:
                envelope = {"status": ExecutionStatus.SUCCESS, "output": serialized_output}
        except Exception as error:
            envelope = {
                "status": ExecutionStatus.FAILED,
                "error_code": type(error).__name__,
                "error_message": str(error)[: min(output_bytes, 4_096)],
            }
    send_connection.send_bytes(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    send_connection.close()


class LocalExecutionAdapter:
    """Execute only trusted registered handlers in bounded child processes."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        workspace_root: str | Path,
        artifact_root: str | Path,
        temporary_root: str | Path | None = None,
    ):
        self.registry = registry
        self.workspace_root = Path(workspace_root).resolve()
        self.artifact_root = Path(artifact_root).resolve()
        self.temporary_root = Path(temporary_root).resolve() if temporary_root else None
        if self.temporary_root is not None:
            self.temporary_root.mkdir(parents=True, exist_ok=True)

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        started = time.monotonic()
        definition = self.registry.resolve(request.tool_name, request.tool_version)
        rejection = self._validate_request(request, definition)
        if rejection is not None:
            return self._result(request, started, **rejection)
        assert definition is not None
        try:
            definition.input_model.model_validate(request.arguments)
            self._validate_paths(request, definition)
        except (ValidationError, ValueError) as error:
            return self._result(
                request,
                started,
                status=ExecutionStatus.INVALID_ARGUMENTS,
                error_code="INVALID_ARGUMENTS",
                error_message=str(error),
            )

        with tempfile.TemporaryDirectory(dir=self.temporary_root) as sandbox:
            sandbox_root = Path(sandbox)
            stdout_path = sandbox_root / "stdout.txt"
            stderr_path = sandbox_root / "stderr.txt"
            receive_connection, send_connection = multiprocessing.Pipe(duplex=False)
            ready_event = multiprocessing.get_context("spawn").Event()
            context = ExecutionContext(
                artifact_root=self.artifact_root,
                workspace_root=self.workspace_root,
                sandbox_root=sandbox_root,
            )
            process = multiprocessing.get_context("spawn").Process(
                target=_child_execute,
                args=(
                    definition,
                    request.arguments,
                    context,
                    request.policy.network,
                    request.budget.memory_megabytes,
                    request.budget.timeout_seconds,
                    request.budget.output_bytes,
                    send_connection,
                    ready_event,
                    str(stdout_path),
                    str(stderr_path),
                ),
            )
            process.start()
            send_connection.close()
            startup_timeout = min(max(request.budget.timeout_seconds * 10, 1), 10)
            if not ready_event.wait(startup_timeout):
                process.terminate()
                process.join(2)
                return self._result(
                    request,
                    started,
                    status=ExecutionStatus.FAILED,
                    error_code="SANDBOX_START_FAILED",
                    error_message="sandbox did not become ready before the startup deadline",
                    stdout=self._bounded_log(stdout_path, request.budget.output_bytes),
                    stderr=self._bounded_log(stderr_path, request.budget.output_bytes),
                )
            deadline = time.monotonic() + request.budget.timeout_seconds
            payload: bytes | None = None
            while time.monotonic() < deadline:
                if receive_connection.poll(0.01):
                    payload = receive_connection.recv_bytes()
                    break
                if not process.is_alive():
                    break
            if payload is None and process.is_alive():
                process.terminate()
                process.join(2)
                return self._result(
                    request,
                    started,
                    status=ExecutionStatus.TIMED_OUT,
                    error_code="TIMEOUT",
                    error_message="tool exceeded its declared timeout",
                    stdout=self._bounded_log(stdout_path, request.budget.output_bytes),
                    stderr=self._bounded_log(stderr_path, request.budget.output_bytes),
                )
            process.join(2)
            if payload is None:
                return self._result(
                    request,
                    started,
                    status=ExecutionStatus.FAILED,
                    error_code="SANDBOX_EXITED",
                    error_message=f"sandbox exited without a result (code {process.exitcode})",
                    stdout=self._bounded_log(stdout_path, request.budget.output_bytes),
                    stderr=self._bounded_log(stderr_path, request.budget.output_bytes),
                )
            envelope = json.loads(payload)
            return self._result(
                request,
                started,
                status=ExecutionStatus(envelope["status"]),
                output=envelope.get("output", {}),
                error_code=envelope.get("error_code"),
                error_message=envelope.get("error_message"),
                stdout=self._bounded_log(stdout_path, request.budget.output_bytes),
                stderr=self._bounded_log(stderr_path, request.budget.output_bytes),
            )

    def _validate_request(
        self, request: ExecutionRequest, definition: ToolDefinition | None
    ) -> dict[str, Any] | None:
        if request.tool_name not in request.policy.allowed_tools:
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "TOOL_NOT_ALLOWED",
                "error_message": "tool is not allowed by sandbox policy",
            }
        if definition is None:
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "TOOL_NOT_REGISTERED",
                "error_message": "tool name and version are not registered",
            }
        missing = definition.required_capabilities - request.policy.allowed_capabilities
        if missing:
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "CAPABILITY_NOT_ALLOWED",
                "error_message": f"required capabilities are not allowed: {sorted(missing)}",
            }
        if request.policy.network is not NetworkPolicy.DENY:
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "LOCAL_NETWORK_MODE_UNSUPPORTED",
                "error_message": "the local adapter supports deny-only network policy",
            }
        if (
            definition.network is not NetworkPolicy.DENY
            and request.policy.network is NetworkPolicy.DENY
        ):
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "NETWORK_NOT_ALLOWED",
                "error_message": "tool requires network access denied by policy",
            }
        if (
            definition.filesystem is FilesystemPolicy.READ_ONLY
            and request.policy.filesystem is not FilesystemPolicy.READ_ONLY
        ):
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "FILESYSTEM_NOT_ALLOWED",
                "error_message": "tool requires read-only filesystem access denied by policy",
            }
        declared = definition.default_budget
        requested = request.budget
        if (
            requested.timeout_seconds > declared.timeout_seconds
            or requested.memory_megabytes > declared.memory_megabytes
            or requested.output_bytes > declared.output_bytes
        ):
            return {
                "status": ExecutionStatus.REJECTED,
                "error_code": "BUDGET_EXCEEDS_TOOL_LIMIT",
                "error_message": "requested resources exceed the tool definition",
            }
        return None

    def _validate_paths(self, request: ExecutionRequest, definition: ToolDefinition) -> None:
        for field in definition.path_arguments:
            value = request.arguments.get(field)
            if not isinstance(value, str):
                raise ValueError(f"path argument {field} must be a string")
            self.resolve_read_path(value, request.policy)

    def resolve_read_path(self, relative_path: str, policy: SandboxPolicy) -> Path:
        if policy.filesystem is not FilesystemPolicy.READ_ONLY:
            raise ValueError("filesystem reads are denied by sandbox policy")
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("path must be repository-relative without parent traversal")
        resolved = (self.workspace_root / candidate).resolve()
        allowed: list[Path] = []
        for root in policy.readable_roots:
            declared_root = Path(root)
            if declared_root.is_absolute() or ".." in declared_root.parts:
                raise ValueError("readable roots must remain inside the repository")
            resolved_root = (self.workspace_root / declared_root).resolve()
            if not resolved_root.is_relative_to(self.workspace_root):
                raise ValueError("readable root resolves outside the repository")
            allowed.append(resolved_root)
        if not any(resolved.is_relative_to(root) for root in allowed):
            raise ValueError("path resolves outside declared readable roots")
        if not resolved.is_file():
            raise ValueError("path must resolve to an existing regular file")
        return resolved

    @staticmethod
    def _bounded_log(path: Path, limit: int) -> str:
        if not path.exists():
            return ""
        return path.read_bytes()[:limit].decode("utf-8", errors="replace")

    @staticmethod
    def _result(
        request: ExecutionRequest,
        started: float,
        *,
        status: ExecutionStatus,
        output: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> ExecutionResult:
        return ExecutionResult(
            request_id=request.request_id,
            run_id=request.run_id,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            status=status,
            output=output or {},
            error_code=error_code,
            error_message=error_message,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=time.monotonic() - started,
            scientific_use_allowed=False,
        )
