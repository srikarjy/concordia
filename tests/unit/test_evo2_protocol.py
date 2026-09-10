from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from concordia.genomics.evo2_protocol import (
    Evo2SourceFilePin,
    Evo2SourcePin,
    Evo2SourceVerifier,
    Evo2StudyProtocolV2,
    score_causal_logits,
)
from concordia.scientific import StudyProtocol

ROOT = Path(__file__).resolve().parents[2]


class FixtureGitReader:
    def __init__(self, revision: str = "a" * 40, status: str = ""):
        self.revision = revision
        self.status = status

    def read(self, checkout: Path, *arguments: str) -> str:
        values = {
            ("remote", "get-url", "origin"): "https://github.com/ArcInstitute/evo2.git",
            ("rev-parse", "HEAD"): self.revision,
            ("status", "--porcelain"): self.status,
        }
        return values[arguments]


def source_checkout(tmp_path: Path) -> tuple[Path, Evo2SourcePin]:
    root = tmp_path / "evo2"
    root.mkdir()
    project = (
        '[project]\nname = "evo2"\nversion = "0.6.0"\n'
        'requires-python = ">=3.11,<3.13"\n'
    )
    (root / "pyproject.toml").write_text(project, encoding="utf-8")
    source = root / "evo2" / "scoring.py"
    source.parent.mkdir()
    source.write_text("scoring source\n", encoding="utf-8")
    files = []
    for relative_path in ("pyproject.toml", "evo2/scoring.py"):
        path = root / relative_path
        files.append(
            Evo2SourceFilePin(
                path=relative_path,
                byte_size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    pin = Evo2SourcePin(
        repository_url="https://github.com/ArcInstitute/evo2.git",
        revision="a" * 40,
        package_version="0.6.0",
        files=tuple(files),
    )
    return root, pin


def test_corrected_hbb_protocol_pins_source_checkpoint_and_shift() -> None:
    original_path = ROOT / "configs/studies/hbb_promoter_protocol.yaml"
    original = StudyProtocol.model_validate(yaml.safe_load(original_path.read_text()))
    corrected = Evo2StudyProtocolV2.model_validate(
        yaml.safe_load(
            (ROOT / "configs/studies/hbb_promoter_evo2_protocol_v2.yaml").read_text()
        )
    )

    assert original.protocol_id == "hbb-promoter-evo2-pilot-v1"
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == (
        "f6f469c0c710a1dbeae0d71b7bcdbb954490c1524bb352ab70b2411e096b24a8"
    )
    assert corrected.supersedes_protocol_id == original.protocol_id
    assert corrected.source.revision == "53f195997257c56c00e5ef8d33a54f5baad143a6"
    assert corrected.source.package_version == "0.6.0"
    assert corrected.checkpoint.revision == "bda0089f92582d5baabf0f22d9fc85f3588f6b58"
    assert corrected.checkpoint.sha256 == (
        "c66645929dc1b9c631f5be656da8726f38946315dc9167000a615dd626fcecf4"
    )
    assert corrected.scoring.causal_token_shift == 1
    assert corrected.scoring.expected_scored_token_count == 8191
    assert corrected.execution_status == "NOT_RUN"
    assert not corrected.scientific_use_allowed


def test_causal_scoring_uses_next_token_and_ignores_last_logit_row() -> None:
    logits = np.array(
        [
            [3.0, 0.0, -1.0, -2.0],
            [-2.0, -1.0, 0.0, 3.0],
            [100.0, -100.0, -100.0, -100.0],
        ]
    )
    tokens = [0, 0, 3]

    result = score_causal_logits(logits, tokens)
    expected_first = 3.0 - np.log(np.exp(logits[0]).sum())
    expected_second = 3.0 - np.log(np.exp(logits[1]).sum())

    assert result.scored_token_count == 2
    assert result.target_token_log_probabilities == pytest.approx(
        (expected_first, expected_second)
    )
    assert result.mean_log_likelihood == pytest.approx(
        (expected_first + expected_second) / 2
    )


def test_causal_scoring_rejects_invalid_logits_and_tokens() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        score_causal_logits(np.array([[0.0, np.nan], [0.0, 1.0]]), [0, 1])
    with pytest.raises(ValueError, match="outside"):
        score_causal_logits(np.zeros((2, 2)), [0, 2])
    with pytest.raises(ValueError, match="match"):
        score_causal_logits(np.zeros((3, 2)), [0, 1])


def test_evo2_source_verifier_checks_pinned_checkout_without_execution(
    tmp_path: Path,
) -> None:
    root, pin = source_checkout(tmp_path)

    result = Evo2SourceVerifier(FixtureGitReader()).verify(root, pin)

    assert result.source_verified
    assert not result.checkpoint_present
    assert result.execution_status == "NOT_RUN"
    assert not result.scientific_use_allowed


def test_evo2_source_verifier_rejects_changed_source(tmp_path: Path) -> None:
    root, pin = source_checkout(tmp_path)
    (root / "evo2/scoring.py").write_text("changed source\n", encoding="utf-8")

    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        Evo2SourceVerifier(FixtureGitReader()).verify(root, pin)


def test_evo2_source_verifier_rejects_symlink(tmp_path: Path) -> None:
    root, pin = source_checkout(tmp_path)
    expected = root / "evo2/scoring.py"
    outside = tmp_path / "outside.py"
    outside.write_bytes(expected.read_bytes())
    expected.unlink()
    expected.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        Evo2SourceVerifier(FixtureGitReader()).verify(root, pin)


def test_evo2_readiness_record_preserves_pre_execution_blockers() -> None:
    record = json.loads(
        (ROOT / "reports/evo2-execution-readiness.json").read_text(encoding="utf-8")
    )

    assert record["source"]["checkout_verified"]
    assert record["checkpoint"]["bytes_staged_and_verified"]
    assert record["zerogpu"]["official_python_requirement_met"]
    assert record["zerogpu"]["evo2_installed"]
    assert record["zerogpu"]["runtime_imports_verified"]
    assert not record["zerogpu"]["checkpoint_deserialized"]
    assert not record["zerogpu"]["model_loaded"]
    assert record["readiness_status"] == "READY_FOR_BOUNDED_MODEL_LOAD_QUALIFICATION"
    assert record["execution_status"] == "NOT_RUN"
    assert not record["scientific_use_allowed"]


def test_zerogpu_runtime_record_preserves_failure_and_no_execution() -> None:
    record = json.loads(
        (ROOT / "reports/evo2-zerogpu-runtime-qualification.json").read_text(
            encoding="utf-8"
        )
    )

    assert record["attempts"][0]["result"] == "FAILED_IMPORT"
    passed = record["attempts"][1]
    assert passed["result"] == "PASSED_RUNTIME_QUALIFICATION"
    assert passed["checkpoint"]["bytes_verified"]
    assert not passed["checkpoint_deserialized"]
    assert not passed["model_loaded"]
    assert not passed["forward_pass_executed"]
    assert passed["execution_status"] == "NOT_RUN"
    assert not passed["scientific_use_allowed"]
