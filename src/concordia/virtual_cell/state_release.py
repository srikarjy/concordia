"""Immutable selection and fail-closed verification of an Arc State release."""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from concordia.virtual_cell.cellxgene import AnndataH5adInspector, H5adInspector

SHA256_PATTERN = r"^[0-9a-f]{64}$"
REVISION_PATTERN = r"^[0-9a-f]{40}$"


class StateReleaseFileRole(StrEnum):
    MODEL_LICENSE = "model_license"
    ACCEPTABLE_USE_POLICY = "acceptable_use_policy"
    CHECKPOINT = "checkpoint"
    CONFIG = "config"
    DATASET = "dataset"
    BATCH_MAP = "batch_map"
    CELL_TYPE_MAP = "cell_type_map"
    DATA_MODULE = "data_module"
    PERTURBATION_MAP = "perturbation_map"
    FEATURE_DIMENSIONS = "feature_dimensions"


class StateReleaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: StateReleaseFileRole
    path: str = Field(min_length=1)
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    media_type: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or value != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("State release file path must be canonical and relative")
        return value


class StateDatasetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_count: int = Field(ge=1)
    gene_count: int = Field(ge=1)
    gene_order_digest: str = Field(pattern=SHA256_PATTERN)
    observation_schema_digest: str = Field(pattern=SHA256_PATTERN)
    cell_context_column: str = Field(min_length=1)
    cell_context_value: str = Field(min_length=1)
    perturbation_column: str = Field(min_length=1)
    control_label: str = Field(min_length=1)
    control_count: int = Field(ge=1)


class StateTermsAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ACCEPTED_BY_USER"] = "ACCEPTED_BY_USER"
    accepted_on: date
    use_scope: Literal["NON_COMMERCIAL"] = "NON_COMMERCIAL"
    commercial_use_allowed: Literal[False] = False


class StateReleaseSelection(BaseModel):
    """A release decision recorded before any State prediction is executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    repository_id: Literal["arcinstitute/ST-HVG-Replogle"]
    repository_url: Literal["https://huggingface.co/arcinstitute/ST-HVG-Replogle"]
    revision: str = Field(pattern=REVISION_PATTERN)
    selected_on: date
    terms: StateTermsAcceptance
    files: tuple[StateReleaseFile, ...] = Field(min_length=1)
    dataset: StateDatasetSchema

    @model_validator(mode="after")
    def validate_file_inventory(self) -> StateReleaseSelection:
        roles = [item.role for item in self.files]
        paths = [item.path for item in self.files]
        if len(set(roles)) != len(roles):
            raise ValueError("State release file roles must be unique")
        if len(set(paths)) != len(paths):
            raise ValueError("State release file paths must be unique")
        missing = set(StateReleaseFileRole) - set(roles)
        extra = set(roles) - set(StateReleaseFileRole)
        if missing or extra:
            raise ValueError(
                "State release file inventory must contain every required role exactly once"
            )
        return self

    def file_for(self, role: StateReleaseFileRole) -> StateReleaseFile:
        return next(item for item in self.files if item.role is role)


class VerifiedStateReleaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: StateReleaseFileRole
    path: str
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=SHA256_PATTERN)


class VerifiedStateDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_count: int = Field(ge=1)
    gene_count: int = Field(ge=1)
    gene_order_digest: str = Field(pattern=SHA256_PATTERN)
    observation_schema_digest: str = Field(pattern=SHA256_PATTERN)
    cell_context_column: str
    cell_context_value: str
    perturbation_column: str
    control_label: str
    control_count: int = Field(ge=1)


class StateReleaseVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    repository_id: str
    revision: str = Field(pattern=REVISION_PATTERN)
    release_verified: Literal[True] = True
    model_terms_accepted: Literal[True] = True
    use_scope: Literal["NON_COMMERCIAL"] = "NON_COMMERCIAL"
    commercial_use_allowed: Literal[False] = False
    files: tuple[VerifiedStateReleaseFile, ...]
    dataset: VerifiedStateDataset
    execution_status: Literal["NOT_RUN"] = "NOT_RUN"
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class StateReleaseVerifier:
    """Verify staged bytes and H5AD metadata without loading serialized model files."""

    def __init__(self, inspector: H5adInspector | None = None):
        self.inspector = inspector or AnndataH5adInspector()

    def verify(
        self,
        root: str | Path,
        selection: StateReleaseSelection,
    ) -> StateReleaseVerification:
        candidate_root = Path(root)
        if not candidate_root.is_dir() or candidate_root.is_symlink():
            raise ValueError("State release root must be a real directory")
        resolved_root = candidate_root.resolve()

        verified_files: list[VerifiedStateReleaseFile] = []
        for expected in selection.files:
            path = self._safe_file(resolved_root, expected.path)
            byte_size = path.stat().st_size
            if byte_size != expected.byte_size:
                raise ValueError(f"State release file size mismatch: {expected.path}")
            digest = _sha256(path)
            if digest != expected.sha256:
                raise ValueError(f"State release file hash mismatch: {expected.path}")
            verified_files.append(
                VerifiedStateReleaseFile(
                    role=expected.role,
                    path=expected.path,
                    byte_size=byte_size,
                    sha256=digest,
                )
            )

        dataset_file = selection.file_for(StateReleaseFileRole.DATASET)
        dataset_path = self._safe_file(resolved_root, dataset_file.path)
        declared = selection.dataset
        observed = self.inspector.inspect(
            dataset_path,
            perturbation_key=declared.perturbation_column,
            cell_context_key=declared.cell_context_column,
        )
        if (observed.cell_count, observed.gene_count) != (
            declared.cell_count,
            declared.gene_count,
        ):
            raise ValueError("State H5AD shape does not match the release selection")
        if observed.gene_order_digest != declared.gene_order_digest:
            raise ValueError("State H5AD gene-order digest does not match")
        if observed.obs_schema_digest != declared.observation_schema_digest:
            raise ValueError("State H5AD observation-schema digest does not match")
        if observed.cell_context_values != (declared.cell_context_value,):
            raise ValueError("State H5AD cell context does not match")
        control_count = observed.perturbation_counts.get(declared.control_label)
        if control_count != declared.control_count:
            raise ValueError("State H5AD control population does not match")

        return StateReleaseVerification(
            repository_id=selection.repository_id,
            revision=selection.revision,
            files=tuple(verified_files),
            dataset=VerifiedStateDataset(
                cell_count=observed.cell_count,
                gene_count=observed.gene_count,
                gene_order_digest=observed.gene_order_digest,
                observation_schema_digest=observed.obs_schema_digest,
                cell_context_column=declared.cell_context_column,
                cell_context_value=declared.cell_context_value,
                perturbation_column=declared.perturbation_column,
                control_label=declared.control_label,
                control_count=control_count,
            ),
            limitations=(
                "Verification reads H5AD metadata but does not load the State checkpoint.",
                "Model execution and biological prediction have not been performed.",
                "The accepted model terms permit non-commercial use only.",
            ),
        )

    @staticmethod
    def _safe_file(root: Path, relative_path: str) -> Path:
        parts = PurePosixPath(relative_path).parts
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"State release path contains a symlink: {relative_path}")
        if not current.is_file():
            raise ValueError(f"State release file is missing: {relative_path}")
        try:
            current.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError(f"State release path escapes its root: {relative_path}") from error
        return current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
