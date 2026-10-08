from __future__ import annotations

import json

from concordia.benchmarks.contracts import BenchmarkStatus
from concordia.benchmarks.runner import (
    run_benchmark_suite,
    run_claim_benchmark,
    run_replay_benchmark,
    run_throughput_benchmark,
)


def test_throughput_benchmark_reports_local_operations() -> None:
    result = run_throughput_benchmark(iterations=2, nodes=3)

    assert result.status is BenchmarkStatus.COMPLETED
    assert result.operation_count == 6
    assert result.latency.sample_count == 2
    assert result.scientific_use_allowed is False


def test_replay_benchmark_requires_exact_manifest_and_artifact_matches() -> None:
    result = run_replay_benchmark(repetitions=3)

    assert result.status is BenchmarkStatus.COMPLETED
    assert result.manifest_replay_matches == 3
    assert result.artifact_replay_matches == 3
    assert result.exact_replay_rate == 1


def test_claim_benchmark_reports_labeled_verifier_metrics() -> None:
    result = run_claim_benchmark(repetitions=1)

    assert result.status is BenchmarkStatus.COMPLETED
    assert result.dataset_id == "synthetic-verifier-cases-v1"
    assert result.sample_count == 5
    assert result.accuracy == 1
    assert result.macro_f1 == 1


def test_benchmark_suite_writes_versioned_json(tmp_path) -> None:
    output = tmp_path / "benchmark.json"
    report = run_benchmark_suite(
        suite="replay",
        repetitions=2,
        output=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert report.status is BenchmarkStatus.COMPLETED
    assert payload["schema_version"] == 1
    assert payload["scientific_use_allowed"] is False
    assert payload["suites"][0]["suite"] == "replay"
