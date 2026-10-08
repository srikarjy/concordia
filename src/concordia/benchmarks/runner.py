"""Benchmark runners for local reproducibility and optional live inference."""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from concordia.benchmarks.contracts import (
    BenchmarkReport,
    BenchmarkStatus,
    BoltzLatencyBenchmark,
    ClaimBenchmark,
    LatencySummary,
    ReplayBenchmark,
    ThroughputBenchmark,
)
from concordia.experiments.schema import (
    CreateExperimentNodeRequest,
    CreateExperimentRequest,
    DnaPayload,
    ExperimentNodeKind,
    ExperimentOperation,
)
from concordia.experiments.service import ExperimentStore
from concordia.genomes.schema import EvidenceFamily
from concordia.genomics.boltz_nvidia import BoltzComplexRequest, NvidiaHostedBoltzRunner
from concordia.storage.content import ContentAddressedStore
from concordia.verification.cross import (
    ClaimRequest,
    EvidenceRecord,
    ProvenanceArtifact,
    Scope,
    SupportStatus,
    verify_claim,
)


def _latency(values: list[float]) -> LatencySummary:
    if not values:
        return LatencySummary(
            sample_count=0,
            minimum_ms=0,
            mean_ms=0,
            p50_ms=0,
            p95_ms=0,
            maximum_ms=0,
        )
    ordered = sorted(values)

    def percentile(rank: float) -> float:
        index = min(len(ordered) - 1, max(0, math.ceil(rank * len(ordered)) - 1))
        return ordered[index]

    return LatencySummary(
        sample_count=len(ordered),
        minimum_ms=ordered[0],
        mean_ms=sum(ordered) / len(ordered),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        maximum_ms=ordered[-1],
    )


def _revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _add_dna_node(
    store: ExperimentStore,
    experiment_id: str,
    sequence: str,
    parent_ids: tuple[str, ...] = (),
    operation: ExperimentOperation = ExperimentOperation.ROOT,
    label: str = "Reference DNA",
) -> str:
    return store.add_node(
        experiment_id,
        CreateExperimentNodeRequest(
            kind=ExperimentNodeKind.DNA_SEQUENCE,
            operation=operation,
            label=label,
            parent_ids=parent_ids,
            payload=DnaPayload(sequence=sequence),
        ),
    ).node_id


def run_throughput_benchmark(*, iterations: int = 10, nodes: int = 25) -> ThroughputBenchmark:
    if iterations < 1 or nodes < 1:
        raise ValueError("iterations and nodes must be positive")
    durations: list[float] = []
    operation_count = 0
    started_total = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="concordia-throughput-") as root:
        store = ExperimentStore(root)
        for iteration in range(iterations):
            experiment = store.create(
                CreateExperimentRequest(title=f"Benchmark {iteration}", description="throughput")
            )
            started = time.perf_counter()
            parent = _add_dna_node(store, experiment.experiment.experiment_id, "ACGT")
            for node_index in range(1, nodes):
                parent = _add_dna_node(
                    store,
                    experiment.experiment.experiment_id,
                    "ACGT" if node_index % 2 else "ACGA",
                    parent_ids=(parent,),
                    operation=ExperimentOperation.EDIT,
                    label=f"Node {node_index}",
                )
            durations.append((time.perf_counter() - started) * 1_000)
            operation_count += nodes
    elapsed_seconds = time.perf_counter() - started_total
    return ThroughputBenchmark(
        status=BenchmarkStatus.COMPLETED,
        operation_count=operation_count,
        elapsed_seconds=elapsed_seconds,
        operations_per_second=operation_count / elapsed_seconds if elapsed_seconds else 0,
        latency=_latency(durations),
        parameters={"iterations": iterations, "nodes_per_iteration": nodes},
    )


def run_replay_benchmark(*, repetitions: int = 10) -> ReplayBenchmark:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    manifest_matches = 0
    artifact_matches = 0
    reasons: list[str] = []
    for repetition in range(repetitions):
        with tempfile.TemporaryDirectory(prefix=f"concordia-replay-{repetition}-") as root:
            store = ExperimentStore(root)
            experiment = store.create(CreateExperimentRequest(title="Replay benchmark"))
            experiment_id = experiment.experiment.experiment_id
            root_id = _add_dna_node(store, experiment_id, "ACGT")
            child_id = _add_dna_node(
                store,
                experiment_id,
                "ACGA",
                parent_ids=(root_id,),
                operation=ExperimentOperation.EDIT,
                label="Replay child",
            )
            first = store.manifest(experiment_id)
            second = store.manifest(experiment_id)
            if first.manifest_digest == second.manifest_digest:
                manifest_matches += 1
            else:
                reasons.append(f"manifest mismatch at repetition {repetition}")
            first_artifacts = tuple(node.artifact_digest for node in first.nodes)
            second_artifacts = tuple(node.artifact_digest for node in second.nodes)
            if first_artifacts == second_artifacts and store.payload(experiment_id, child_id):
                artifact_matches += 1
            else:
                reasons.append(f"artifact mismatch at repetition {repetition}")
    exact = min(manifest_matches, artifact_matches) / repetitions
    return ReplayBenchmark(
        status=BenchmarkStatus.COMPLETED,
        repetitions=repetitions,
        manifest_replay_matches=manifest_matches,
        artifact_replay_matches=artifact_matches,
        exact_replay_rate=exact,
        mismatch_reasons=tuple(reasons),
    )


def _scope() -> Scope:
    return Scope(
        assembly="benchmark-v1",
        chromosome="synthetic",
        strand="+",
        start=0,
        end=12,
        model_checkpoint="benchmark-verifier-v1",
        scoring_target="labeled_claim_status",
        assay="synthetic benchmark",
    )


def _artifact(
    store: ContentAddressedStore,
    *,
    kind: str,
    payload: dict[str, object],
    dependencies: tuple[str, ...] = (),
    scientific_use_allowed: bool = True,
    execution_mode: str = "real",
) -> str:
    payload_digest = store.put_json(payload)
    envelope = ProvenanceArtifact.model_validate(
        {
            "kind": kind,
            "payload_digest": payload_digest,
            "dependencies": dependencies,
            "execution_mode": execution_mode,
            "scientific_use_allowed": scientific_use_allowed,
            "source": "synthetic benchmark fixture",
            "producing_tool": "claim-benchmark-v1",
        }
    )
    return store.put_json(envelope.model_dump(mode="json"))


def _claim_case(store: ContentAddressedStore, label: str) -> ClaimRequest:
    sequence = _artifact(store, kind="sequence", payload={"sequence": "ACGTACGTACGT"})
    scope = _scope()
    if label == SupportStatus.SUPPORTED.value:
        counterfactual = _artifact(
            store, kind="evidence", payload={"case": label}, dependencies=(sequence,)
        )
        annotation = _artifact(
            store, kind="evidence", payload={"case": label}, dependencies=(sequence,)
        )
        evidence = (
            EvidenceRecord(
                evidence_id="counterfactual",
                family=EvidenceFamily.COUNTERFACTUAL,
                method="mutational_scan",
                independence_group="model-a",
                artifact_digest=counterfactual,
                scope=scope,
                assessment="supports",
                strength=0.9,
                counterfactual_passed=True,
            ),
            EvidenceRecord(
                evidence_id="annotation",
                family=EvidenceFamily.BIOLOGICAL_ANNOTATION,
                method="interval_overlap",
                independence_group="annotation-a",
                artifact_digest=annotation,
                scope=scope,
                assessment="supports",
                strength=0.9,
            ),
        )
    elif label == SupportStatus.PARTIALLY_SUPPORTED.value:
        artifact = _artifact(
            store, kind="evidence", payload={"case": label}, dependencies=(sequence,)
        )
        evidence = (
            EvidenceRecord(
                evidence_id="counterfactual",
                family=EvidenceFamily.COUNTERFACTUAL,
                method="mutational_scan",
                independence_group="model-a",
                artifact_digest=artifact,
                scope=scope,
                assessment="supports",
                strength=0.9,
                counterfactual_passed=True,
            ),
        )
    elif label == SupportStatus.CONTRADICTED.value:
        artifact = _artifact(
            store, kind="evidence", payload={"case": label}, dependencies=(sequence,)
        )
        evidence = (
            EvidenceRecord(
                evidence_id="contradiction",
                family=EvidenceFamily.BIOLOGICAL_ANNOTATION,
                method="independent_assay",
                independence_group="assay-a",
                artifact_digest=artifact,
                scope=scope,
                assessment="contradicts",
                strength=0.9,
                critical=True,
            ),
        )
    elif label == SupportStatus.UNVERIFIABLE.value:
        artifact = _artifact(
            store,
            kind="evidence",
            payload={"case": label},
            dependencies=(sequence,),
            scientific_use_allowed=False,
            execution_mode="fixture",
        )
        evidence = (
            EvidenceRecord(
                evidence_id="fixture",
                family=EvidenceFamily.COUNTERFACTUAL,
                method="mutational_scan",
                independence_group="fixture-a",
                artifact_digest=artifact,
                scope=scope,
                assessment="supports",
                strength=0.9,
                counterfactual_passed=True,
            ),
        )
    else:
        evidence = ()
    return ClaimRequest(
        claim_id=f"case-{label.lower()}",
        text=f"Synthetic {label} case",
        scope=scope,
        source_sequence=sequence,
        evidence=evidence,
    )


def run_claim_benchmark(*, repetitions: int = 1) -> ClaimBenchmark:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    labels = tuple(status.value for status in SupportStatus)
    pairs: list[tuple[str, str]] = []
    for _ in range(repetitions):
        with tempfile.TemporaryDirectory(prefix="concordia-claims-") as root:
            store = ContentAddressedStore(root)
            for expected in labels:
                predicted = verify_claim(_claim_case(store, expected), store).status.value
                pairs.append((expected, predicted))
    matrix = {expected: {predicted: 0 for predicted in labels} for expected in labels}
    for expected, predicted in pairs:
        matrix[expected][predicted] += 1
    correct = sum(matrix[label][label] for label in labels)
    precision_values: list[float] = []
    recall_values: list[float] = []
    f1_values: list[float] = []
    for label in labels:
        true_positive = matrix[label][label]
        predicted_total = sum(matrix[expected][label] for expected in labels)
        actual_total = sum(matrix[label].values())
        precision = true_positive / predicted_total if predicted_total else 0
        recall = true_positive / actual_total if actual_total else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        precision_values.append(precision)
        recall_values.append(recall)
        f1_values.append(f1)
    count = len(pairs)
    return ClaimBenchmark(
        status=BenchmarkStatus.COMPLETED,
        dataset_id="synthetic-verifier-cases-v1",
        sample_count=count,
        accuracy=correct / count if count else 0,
        macro_precision=sum(precision_values) / len(labels),
        macro_recall=sum(recall_values) / len(labels),
        macro_f1=sum(f1_values) / len(labels),
        confusion_matrix=matrix,
        labels=labels,
    )


def run_boltz_latency_benchmark(
    *, repetitions: int = 1, real: bool = False
) -> BoltzLatencyBenchmark:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    parameters = {"repetitions": repetitions, "real_requested": real}
    if not real or not os.environ.get("NVIDIA_API_KEY"):
        reason = (
            "Pass --real with NVIDIA_API_KEY to run hosted latency measurement."
            if not real
            else "NVIDIA_API_KEY is not configured."
        )
        return BoltzLatencyBenchmark(
            status=BenchmarkStatus.NOT_RUN,
            model_id="mit/boltz2",
            sample_count=0,
            successful_count=0,
            failed_count=0,
            latency=None,
            parameters=parameters,
            error_messages=(reason,),
        )
    request = BoltzComplexRequest(
        polymers=(
            {"id": "H", "sequence": "EVQLVESGGGLVQPGGSLRLSCAAS"},
            {"id": "L", "sequence": "DIQMTQSPSSLSASVGDRVTITC"},
            {"id": "A", "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"},
        )
    )
    latencies: list[float] = []
    errors: list[str] = []
    successful = 0
    with tempfile.TemporaryDirectory(prefix="concordia-boltz-benchmark-") as root:
        runner = NvidiaHostedBoltzRunner(ContentAddressedStore(Path(root) / "artifacts"))
        for _ in range(repetitions):
            started = time.perf_counter()
            try:
                runner.predict_complex(request)
            except Exception as error:  # report provider failures in the benchmark output
                errors.append(type(error).__name__ + ": " + str(error)[:300])
            else:
                successful += 1
                latencies.append((time.perf_counter() - started) * 1_000)
    return BoltzLatencyBenchmark(
        status=BenchmarkStatus.COMPLETED if successful else BenchmarkStatus.FAILED,
        model_id="mit/boltz2",
        sample_count=repetitions,
        successful_count=successful,
        failed_count=repetitions - successful,
        latency=_latency(latencies) if latencies else None,
        error_messages=tuple(errors),
        parameters=parameters,
    )


def run_benchmark_suite(
    *,
    suite: str = "all",
    output: str | Path | None = None,
    iterations: int = 10,
    nodes: int = 25,
    repetitions: int = 10,
    boltz_repetitions: int = 1,
    real_boltz: bool = False,
) -> BenchmarkReport:
    valid = {"all", "throughput", "replay", "claims", "boltz"}
    if suite not in valid:
        raise ValueError(f"suite must be one of {sorted(valid)}")
    suites = []
    if suite in {"all", "throughput"}:
        suites.append(run_throughput_benchmark(iterations=iterations, nodes=nodes))
    if suite in {"all", "replay"}:
        suites.append(run_replay_benchmark(repetitions=repetitions))
    if suite in {"all", "claims"}:
        suites.append(run_claim_benchmark(repetitions=repetitions))
    if suite in {"all", "boltz"}:
        suites.append(
            run_boltz_latency_benchmark(repetitions=boltz_repetitions, real=real_boltz)
        )
    report = BenchmarkReport(
        benchmark_id="concordia-benchmark-v1-" + uuid.uuid4().hex[:12],
        repository_revision=_revision(),
        status=BenchmarkStatus.COMPLETED,
        suites=tuple(suites),
    )
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report
