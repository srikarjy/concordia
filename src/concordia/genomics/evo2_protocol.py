"""Pinned Evo2 execution protocol and causal likelihood semantics."""

from __future__ import annotations

import hashlib
import math
import subprocess
import tomllib
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from concordia.scientific.protocol import StudyProtocol

SHA256_PATTERN = r"^[0-9a-f]{64}$"
REVISION_PATTERN = r"^[0-9a-f]{40}$"


class Evo2SourceFilePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or value != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("Evo2 source file path must be canonical and relative")
        return value


class Evo2SourcePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_url: Literal["https://github.com/ArcInstitute/evo2.git"]
    revision: str = Field(pattern=REVISION_PATTERN)
    package_name: Literal["evo2"] = "evo2"
    package_version: str = Field(min_length=1)
    python_constraint: Literal[">=3.11,<3.13"] = ">=3.11,<3.13"
    files: tuple[Evo2SourceFilePin, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_files(self) -> Evo2SourcePin:
        paths = [item.path for item in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("Evo2 source file paths must be unique")
        return self


class Evo2CheckpointPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: Literal["arcinstitute/evo2_7b"]
    revision: str = Field(pattern=REVISION_PATTERN)
    filename: Literal["evo2_7b.pt"] = "evo2_7b.pt"
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    config_filename: Literal["config.json"] = "config.json"
    config_byte_size: int = Field(ge=1)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    license: Literal["Apache-2.0"] = "Apache-2.0"


class Evo2ScoringSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: Literal["mean_next_base_log_likelihood"]
    tokenizer: Literal["CharLevelTokenizer-vocab-512"]
    prepend_bos: Literal[False] = False
    causal_token_shift: Literal[1] = 1
    reduction: Literal["mean"] = "mean"
    strand_mode: Literal["forward_only"] = "forward_only"
    variant_delta: Literal["alternate_minus_reference"] = "alternate_minus_reference"
    expected_sequence_length: Literal[8192] = 8192
    expected_scored_token_count: Literal[8191] = 8191
    use_optional_kernels: Literal[False] = False
    retained_score_artifacts: tuple[
        Literal[
            "token_ids",
            "target_token_log_probabilities_float32",
            "sum_log_likelihood_float64",
            "mean_log_likelihood_float64",
        ],
        ...,
    ] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_shift(self) -> Evo2ScoringSemantics:
        if self.expected_scored_token_count != self.expected_sequence_length - 1:
            raise ValueError("Evo2 scored-token count must reflect the one-token causal shift")
        if len(set(self.retained_score_artifacts)) != 4:
            raise ValueError("Evo2 retained score artifacts must be unique and complete")
        return self


class Evo2StudyProtocolV2(StudyProtocol):
    """Corrected frozen study protocol with immutable execution identities."""

    supersedes_protocol_id: str = Field(min_length=1)
    correction_reason: tuple[str, ...] = Field(min_length=1)
    source: Evo2SourcePin
    checkpoint: Evo2CheckpointPin
    scoring: Evo2ScoringSemantics
    execution_status: Literal["NOT_RUN"] = "NOT_RUN"
    scientific_use_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_evo2_scope(self) -> Evo2StudyProtocolV2:
        if self.schema_version != 2:
            raise ValueError("corrected Evo2 protocol must use schema version 2")
        expected_checkpoint = (
            f"{self.checkpoint.repository_id}@{self.checkpoint.revision}/"
            f"{self.checkpoint.filename}"
        )
        if self.model_checkpoint != expected_checkpoint:
            raise ValueError("Evo2 model checkpoint identity does not match its immutable pin")
        if self.scoring_target != self.scoring.target:
            raise ValueError("Evo2 scoring target does not match its declared semantics")
        if self.window_size != self.scoring.expected_sequence_length:
            raise ValueError("Evo2 study window does not match its scoring contract")
        if self.protocol_id == self.supersedes_protocol_id:
            raise ValueError("a corrected Evo2 protocol cannot supersede itself")
        return self


class Evo2GitReader(Protocol):
    def read(self, checkout: Path, *arguments: str) -> str: ...


class SubprocessEvo2GitReader:
    def read(self, checkout: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(checkout), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()


class Evo2SourceVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_url: str
    revision: str = Field(pattern=REVISION_PATTERN)
    package_version: str
    source_verified: Literal[True] = True
    checkpoint_present: Literal[False] = False
    execution_status: Literal["NOT_RUN"] = "NOT_RUN"
    scientific_use_allowed: Literal[False] = False


class Evo2SourceVerifier:
    """Verify pinned Evo2 code without importing it or loading a checkpoint."""

    def __init__(self, git: Evo2GitReader | None = None):
        self.git = git or SubprocessEvo2GitReader()

    def verify(self, checkout: str | Path, pin: Evo2SourcePin) -> Evo2SourceVerification:
        candidate = Path(checkout)
        if not candidate.is_dir() or candidate.is_symlink():
            raise ValueError("Evo2 checkout must be a real directory")
        root = candidate.resolve()
        if self.git.read(root, "remote", "get-url", "origin") != pin.repository_url:
            raise ValueError("Evo2 checkout remote does not match the pin")
        if self.git.read(root, "rev-parse", "HEAD") != pin.revision:
            raise ValueError("Evo2 checkout revision does not match the pin")
        if self.git.read(root, "status", "--porcelain"):
            raise ValueError("Evo2 checkout contains uncommitted changes")

        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        if project.get("name") != pin.package_name:
            raise ValueError("Evo2 package name does not match the pin")
        if project.get("version") != pin.package_version:
            raise ValueError("Evo2 package version does not match the pin")
        if project.get("requires-python") != pin.python_constraint:
            raise ValueError("Evo2 Python constraint does not match the pin")

        for expected in pin.files:
            path = _safe_file(root, expected.path)
            if path.stat().st_size != expected.byte_size:
                raise ValueError(f"Evo2 source file size mismatch: {expected.path}")
            if _sha256(path) != expected.sha256:
                raise ValueError(f"Evo2 source file hash mismatch: {expected.path}")

        return Evo2SourceVerification(
            repository_url=pin.repository_url,
            revision=pin.revision,
            package_version=pin.package_version,
        )


class CausalLikelihoodResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scored_token_count: int = Field(ge=1)
    sum_log_likelihood: float
    mean_log_likelihood: float
    target_token_log_probabilities: tuple[float, ...]

    @model_validator(mode="after")
    def validate_values(self) -> CausalLikelihoodResult:
        values = (
            self.sum_log_likelihood,
            self.mean_log_likelihood,
            *self.target_token_log_probabilities,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Evo2 likelihood artifact contains non-finite values")
        if len(self.target_token_log_probabilities) != self.scored_token_count:
            raise ValueError("Evo2 likelihood artifact has the wrong token count")
        return self


def score_causal_logits(
    logits: np.ndarray,
    token_ids: Sequence[int],
) -> CausalLikelihoodResult:
    """Score token i+1 from logits at i, matching the pinned official Evo2 scorer."""

    values = np.asarray(logits)
    tokens = np.asarray(token_ids, dtype=np.int64)
    if values.ndim != 2:
        raise ValueError("Evo2 logits must have shape (sequence_length, vocabulary_size)")
    if tokens.ndim != 1 or tokens.shape[0] != values.shape[0]:
        raise ValueError("Evo2 token IDs must match the logits sequence dimension")
    if values.shape[0] < 2 or values.shape[1] < 1:
        raise ValueError("Evo2 logits are too small for causal scoring")
    if not np.isfinite(values).all():
        raise ValueError("Evo2 logits contain non-finite values")
    targets = tokens[1:]
    if np.any(targets < 0) or np.any(targets >= values.shape[1]):
        raise ValueError("Evo2 target token ID is outside the logits vocabulary")

    predictors = values[:-1].astype(np.float64, copy=False)
    maxima = predictors.max(axis=1)
    log_normalizers = maxima + np.log(
        np.exp(predictors - maxima[:, np.newaxis]).sum(axis=1)
    )
    target_logits = predictors[np.arange(targets.shape[0]), targets]
    log_probabilities = target_logits - log_normalizers
    total = float(log_probabilities.sum(dtype=np.float64))
    mean = float(total / log_probabilities.shape[0])
    return CausalLikelihoodResult(
        scored_token_count=int(log_probabilities.shape[0]),
        sum_log_likelihood=total,
        mean_log_likelihood=mean,
        target_token_log_probabilities=tuple(float(value) for value in log_probabilities),
    )


def _safe_file(root: Path, relative_path: str) -> Path:
    current = root
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Evo2 source path contains a symlink: {relative_path}")
    if not current.is_file():
        raise ValueError(f"Evo2 source file is missing: {relative_path}")
    try:
        current.resolve().relative_to(root)
    except ValueError as error:
        raise ValueError(f"Evo2 source path escapes its root: {relative_path}") from error
    return current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
