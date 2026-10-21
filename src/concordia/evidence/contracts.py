"""Versioned evidence records for individual model executions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    endpoint: str | None = None
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    params_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    raw_output_ref: str = Field(min_length=1)
    verification_status: Literal["supported", "unverifiable", "refused"]
    verification_reasons: tuple[str, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def _missing_params_requires_unverifiable(self) -> ModelRunEvidence:
        if self.params_hash is None:
            if self.verification_status != "unverifiable":
                raise ValueError("params_hash is None requires verification_status='unverifiable'")
            if not self.verification_reasons:
                raise ValueError("params_hash is None requires at least one verification reason")
        return self
