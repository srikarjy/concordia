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
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
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


def _parse_lock(text: str) -> dict[str, tuple[str, int]]:
    """Pinned version and hash count per package in a --generate-hashes lock."""
    pinned: dict[str, tuple[str, int]] = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==([^\s\\]+)", line)
        if match:
            current = match.group(1).lower().replace("_", "-")
            pinned[current] = (match.group(2), 0)
        elif "--hash=sha256:" in line and current:
            version, count = pinned[current]
            pinned[current] = (version, count + 1)
    return pinned


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def test_space_image_installs_only_the_hash_pinned_lock() -> None:
    """A rebuild of the public image must install the same bytes, not a fresh resolution."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    install = next(
        line for line in dockerfile.splitlines() if "pip install" in line and "-r" in line
    )

    assert "--require-hashes" in install
    assert "requirements-space.lock.txt" in install
    assert "-r requirements-space.txt" not in install


def test_every_declared_space_requirement_is_pinned_within_its_range() -> None:
    """Catches editing requirements-space.txt without running make space-lock."""
    pinned = _parse_lock((ROOT / "requirements-space.lock.txt").read_text())
    declared = [
        line.strip()
        for line in (ROOT / "requirements-space.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert declared

    for requirement in declared:
        name, _, specifiers = requirement.partition(">=")
        name = re.split(r"[\[>=<]", name)[0].strip().lower()
        assert name in pinned, f"{name} is declared but not in the lock"
        version, hashes = pinned[name]
        assert hashes, f"{name}=={version} is pinned without a hash"
        lower, _, upper = specifiers.partition(",<")
        assert _version(version) >= _version(lower), f"{name}=={version} is below >={lower}"
        if upper:
            assert _version(version) < _version(upper), f"{name}=={version} is not <{upper}"
