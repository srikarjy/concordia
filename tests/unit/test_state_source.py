from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from concordia.virtual_cell.state_source import StateCheckoutVerifier, StateSourcePin


class FixtureGitReader:
    def __init__(self, revision: str = "a" * 40, status: str = ""):
        self.revision = revision
        self.status = status

    def read(self, checkout: Path, *arguments: str) -> str:
        assert checkout.is_dir()
        values = {
            ("remote", "get-url", "origin"): "https://github.com/ArcInstitute/state.git",
            ("rev-parse", "HEAD"): self.revision,
            ("status", "--porcelain"): self.status,
        }
        return values[arguments]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def checkout(tmp_path: Path) -> tuple[Path, StateSourcePin]:
    root = tmp_path / "state"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "arc-state"\nversion = "0.11.3"\nrequires-python = ">=3.11,<3.13"\n',
        encoding="utf-8",
    )
    files = {
        "LICENSE": "source license",
        "MODEL_LICENSE.md": "model license",
        "MODEL_ACCEPTABLE_USE_POLICY.md": "acceptable use",
    }
    for name, value in files.items():
        (root / name).write_text(value, encoding="utf-8")
    pin = StateSourcePin(
        repository_url="https://github.com/ArcInstitute/state.git",
        revision="a" * 40,
        package_version="0.11.3",
        python_constraint=">=3.11,<3.13",
        source_license_digest=digest(files["LICENSE"]),
        model_license_digest=digest(files["MODEL_LICENSE.md"]),
        acceptable_use_policy_digest=digest(files["MODEL_ACCEPTABLE_USE_POLICY.md"]),
        audited_at="2026-09-10",
    )
    return root, pin


def test_state_checkout_verifies_source_without_accepting_model_terms(
    tmp_path: Path,
) -> None:
    root, pin = checkout(tmp_path)
    result = StateCheckoutVerifier(FixtureGitReader()).verify(root, pin)

    assert result.source_code_verified
    assert not result.model_weights_present
    assert not result.model_terms_accepted
    assert not result.scientific_use_allowed


def test_state_checkout_rejects_wrong_revision_or_dirty_tree(tmp_path: Path) -> None:
    root, pin = checkout(tmp_path)
    with pytest.raises(ValueError, match="revision"):
        StateCheckoutVerifier(FixtureGitReader(revision="b" * 40)).verify(root, pin)
    with pytest.raises(ValueError, match="uncommitted"):
        StateCheckoutVerifier(FixtureGitReader(status=" M README.md")).verify(root, pin)


def test_state_checkout_rejects_symlink(tmp_path: Path) -> None:
    root, pin = checkout(tmp_path)
    symlink = tmp_path / "state-link"
    symlink.symlink_to(root, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        StateCheckoutVerifier(FixtureGitReader()).verify(symlink, pin)
