from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _uses_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            item
            for child in value.values()
            for item in _uses_values(child)
        ]
    if isinstance(value, list):
        return [item for child in value for item in _uses_values(child)]
    if isinstance(value, str) and "@" in value:
        return [value]
    return []


def test_ci_actions_are_immutable_and_token_is_read_only() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())

    assert workflow["permissions"] == {"contents": "read"}
    action_refs = _uses_values(workflow["jobs"])
    assert action_refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)


def test_public_container_selects_non_root_user_before_startup() -> None:
    instructions = [
        line.strip()
        for line in (ROOT / "Dockerfile").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    final_stage = instructions[instructions.index("FROM python:3.13-slim") :]
    user_index = next(index for index, line in enumerate(final_stage) if line.startswith("USER "))
    command_index = next(index for index, line in enumerate(final_stage) if line.startswith("CMD "))

    assert final_stage[user_index] not in {"USER root", "USER 0"}
    assert user_index < command_index


def test_public_runtime_qualification_is_process_cached() -> None:
    tree = ast.parse((ROOT / "deploy/hf-evo2-worker/app.py").read_text())
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    cached = functions["_qualify_runtime_once"]
    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "lru_cache"
        and any(keyword.arg == "maxsize" and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == 1 for keyword in decorator.keywords)
        for decorator in cached.decorator_list
    )
