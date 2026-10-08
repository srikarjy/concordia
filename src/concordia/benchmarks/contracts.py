"""Versioned benchmark result contracts.

Benchmark reports measure software behavior and model-service behavior. They
are never treated as biological validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NOT_RUN = "NOT_RUN"
    FAILED = "FAILED"


class LatencySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    sample_count: int = Field(ge=0)
    minimum_ms: float = Field(ge=0)
    mean_ms: float = Field(ge=0)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    maximum_ms: float = Field(ge=0)


class ThroughputBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    suite: Literal["throughput"] = "throughput"
    status: BenchmarkStatus
    operation_count: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    operations_per_second: float = Field(ge=0)
    latency: LatencySummary
    parameters: dict[str, int]
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Measures local Concordia persistence and orchestration overhead only.",
        "It is not a model-quality or biological-performance benchmark.",
    )


class ReplayBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: Literal["replay"] = "replay"
    status: BenchmarkStatus
    repetitions: int = Field(ge=0)
    manifest_replay_matches: int = Field(ge=0)
    artifact_replay_matches: int = Field(ge=0)
    exact_replay_rate: float = Field(ge=0, le=1)
    mismatch_reasons: tuple[str, ...] = ()
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Replay equality covers persisted manifests and content-addressed payloads.",
        "It does not establish scientific reproducibility of an external model.",
    )


class ClaimBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: Literal["claims"] = "claims"
    status: BenchmarkStatus
    dataset_id: str
    sample_count: int = Field(ge=0)
    accuracy: float = Field(ge=0, le=1)
    macro_precision: float = Field(ge=0, le=1)
    macro_recall: float = Field(ge=0, le=1)
    macro_f1: float = Field(ge=0, le=1)
    confusion_matrix: dict[str, dict[str, int]]
    labels: tuple[str, ...]
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = (
        "The evaluation set is synthetic and tests verifier logic, not biological truth.",
        "A real scientific claim benchmark requires independently labeled evidence.",
    )


class BoltzLatencyBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    suite: Literal["boltz"] = "boltz"
    status: BenchmarkStatus
    model_id: str
    sample_count: int = Field(ge=0)
    successful_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    latency: LatencySummary | None = None
    error_messages: tuple[str, ...] = ()
    parameters: dict[str, Any]
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Latency measures the hosted service path, including queue and network time.",
        "It is not a structure-quality or binding-affinity benchmark.",
    )


BenchmarkSuite = ThroughputBenchmark | ReplayBenchmark | ClaimBenchmark | BoltzLatencyBenchmark


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    benchmark_id: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    repository_revision: str = Field(min_length=1)
    status: BenchmarkStatus
    suites: tuple[BenchmarkSuite, ...]
    scientific_use_allowed: Literal[False] = False
    interpretation: str = (
        "Benchmark metrics describe Concordia software behavior or an external service call; "
        "they do not establish biological validity."
    )
