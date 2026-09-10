"""Integrity checks for an unexecuted, pinned Arc State source checkout."""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_REVISION_PATTERN = r"^[0-9a-f]{40}$"


class StateSourcePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    repository_url: Literal["https://github.com/ArcInstitute/state.git"]
    revision: str = Field(pattern=GIT_REVISION_PATTERN)
    package_name: Literal["arc-state"] = "arc-state"
    package_version: str = Field(min_length=1)
    python_constraint: str = Field(min_length=1)
    source_license_digest: str = Field(pattern=SHA256_PATTERN)
    model_license_digest: str = Field(pattern=SHA256_PATTERN)
    acceptable_use_policy_digest: str = Field(pattern=SHA256_PATTERN)
    audited_at: str = Field(min_length=1)
    model_terms_status: Literal["NOT_ACCEPTED"] = "NOT_ACCEPTED"


class StateGitReader(Protocol):
    def read(self, checkout: Path, *arguments: str) -> str: ...


class SubprocessStateGitReader:
    def read(self, checkout: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(checkout), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()


class StateCheckoutVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    repository_url: str
    revision: str = Field(pattern=GIT_REVISION_PATTERN)
    package_version: str
    source_code_verified: Literal[True] = True
    model_weights_present: Literal[False] = False
    model_terms_accepted: Literal[False] = False
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class StateCheckoutVerifier:
    """Verify source identity without importing or executing State code."""

    def __init__(self, git: StateGitReader | None = None):
        self.git = git or SubprocessStateGitReader()

    def verify(self, checkout: str | Path, pin: StateSourcePin) -> StateCheckoutVerification:
        candidate = Path(checkout)
        if not candidate.is_dir() or candidate.is_symlink():
            raise ValueError("State checkout must be a real directory")
        root = candidate.resolve()
        if self.git.read(root, "remote", "get-url", "origin") != pin.repository_url:
            raise ValueError("State checkout remote does not match the pinned repository")
        if self.git.read(root, "rev-parse", "HEAD") != pin.revision:
            raise ValueError("State checkout revision does not match the pin")
        if self.git.read(root, "status", "--porcelain"):
            raise ValueError("State checkout contains uncommitted changes")
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        if project.get("name") != pin.package_name:
            raise ValueError("State package name does not match the pin")
        if project.get("version") != pin.package_version:
            raise ValueError("State package version does not match the pin")
        if project.get("requires-python") != pin.python_constraint:
            raise ValueError("State Python constraint does not match the pin")
        expected = {
            "LICENSE": pin.source_license_digest,
            "MODEL_LICENSE.md": pin.model_license_digest,
            "MODEL_ACCEPTABLE_USE_POLICY.md": pin.acceptable_use_policy_digest,
        }
        for relative_path, expected_digest in expected.items():
            path = root / relative_path
            if not path.is_file() or _sha256(path) != expected_digest:
                raise ValueError(f"State source policy file changed: {relative_path}")
        return StateCheckoutVerification(
            repository_url=pin.repository_url,
            revision=pin.revision,
            package_version=pin.package_version,
            limitations=(
                "Source verification does not accept the State model license.",
                "No model weights or biological predictions were loaded.",
                "Real State execution requires a separately isolated Python 3.11 or 3.12 runtime.",
            ),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
