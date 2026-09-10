"""Contracts for population-level cellular perturbation prediction."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class StateInputArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adata_digest: str = Field(pattern=SHA256_PATTERN)
    media_type: Literal["application/x-hdf5-anndata"] = "application/x-hdf5-anndata"
    cell_count: int = Field(ge=1)
    gene_count: int = Field(ge=1)
    gene_order_digest: str = Field(pattern=SHA256_PATTERN)
    preprocessing_version: str = Field(min_length=1)
    cell_context_key: str = Field(min_length=1)
    perturbation_key: str = Field(min_length=1)


class StatePerturbation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["genetic", "chemical", "cytokine"]
    identifier: str = Field(min_length=1)
    dose: str | None = None
    duration: str | None = None


class StateResourceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_cells: int = Field(default=10_000, ge=1, le=1_000_000)
    max_genes: int = Field(default=5_000, ge=1, le=100_000)
    timeout_seconds: int = Field(default=300, ge=1, le=3_600)
    memory_megabytes: int = Field(default=8_192, ge=256, le=262_144)
    output_bytes: int = Field(default=100_000_000, ge=1_024, le=5_000_000_000)


class StatePredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    checkpoint_digest: str = Field(pattern=SHA256_PATTERN)
    input: StateInputArtifact
    perturbation: StatePerturbation
    cell_context: str = Field(min_length=1)
    target: Literal["post_perturbation_gene_expression"] = (
        "post_perturbation_gene_expression"
    )
    budget: StateResourceBudget = Field(default_factory=StateResourceBudget)
    network_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_budget(self) -> StatePredictionRequest:
        if self.input.cell_count > self.budget.max_cells:
            raise ValueError("input cell count exceeds the State sandbox budget")
        if self.input.gene_count > self.budget.max_genes:
            raise ValueError("input gene count exceeds the State sandbox budget")
        return self


class StatePredictionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1)
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    model_id: str = Field(min_length=1)
    checkpoint_digest: str = Field(pattern=SHA256_PATTERN)
    input_adata_digest: str = Field(pattern=SHA256_PATTERN)
    prediction_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    output_cell_count: int = Field(ge=1)
    output_gene_count: int = Field(ge=1)
    execution_mode: Literal["real", "recorded_real", "recorded_fixture"]
    scientific_use_allowed: bool = False
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_eligibility(self) -> StatePredictionResult:
        if self.execution_mode == "recorded_fixture" and self.scientific_use_allowed:
            raise ValueError("fixture State output cannot permit scientific use")
        return self
