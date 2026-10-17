"""Retrospective, leakage-aware benchmark harness for campaign predictors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from math import sqrt

from concordia.campaigns.training import (
    ProteinTrainingExample,
    freeze_protein_dataset,
    train_protein_baseline,
)


@dataclass(frozen=True)
class BenchmarkRun:
    seed: int
    dataset_digest: str
    predictor_metrics: dict[str, float | int]
    constant_baseline_metrics: dict[str, float | int]


@dataclass(frozen=True)
class RetrospectiveBenchmark:
    model_id: str
    runs: tuple[BenchmarkRun, ...]
    prospective_claim_allowed: bool = False
    scientific_use_allowed: bool = False


def run_retrospective_benchmark(
    examples: tuple[ProteinTrainingExample, ...],
    *,
    seeds: tuple[int, ...] = (0, 1, 2),
    test_fraction: float = 0.2,
) -> RetrospectiveBenchmark:
    """Compare the sequence baseline with a train-only constant predictor."""
    if not examples:
        raise ValueError("benchmark requires labeled examples")
    if not seeds:
        raise ValueError("benchmark requires at least one seed")
    runs: list[BenchmarkRun] = []
    for seed in seeds:
        dataset = freeze_protein_dataset(
            f"retrospective:{seed}", examples, test_fraction=test_fraction, seed=seed
        )
        result = train_protein_baseline(dataset)
        by_id = {example.candidate_id: example for example in dataset.examples}
        train_values = [by_id[candidate_id].value for candidate_id in dataset.train_ids]
        test_values = [by_id[candidate_id].value for candidate_id in dataset.test_ids]
        constant = sum(train_values) / len(train_values)
        constant_errors = [constant - actual for actual in test_values]
        runs.append(
            BenchmarkRun(
                seed=seed,
                dataset_digest=dataset.dataset_digest,
                predictor_metrics=result.metrics["test"],
                constant_baseline_metrics={
                    "n": len(test_values),
                    "mae": sum(abs(error) for error in constant_errors) / len(constant_errors),
                    "rmse": sqrt(
                        sum(error * error for error in constant_errors) / len(constant_errors)
                    ),
                },
            )
        )
    return RetrospectiveBenchmark(model_id="protein_composition_ridge_v1", runs=tuple(runs))


def benchmark_digest(benchmark: RetrospectiveBenchmark) -> str:
    """Return a stable content digest for a completed benchmark result."""
    serialized = json.dumps(asdict(benchmark), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "BenchmarkRun",
    "RetrospectiveBenchmark",
    "benchmark_digest",
    "run_retrospective_benchmark",
]
