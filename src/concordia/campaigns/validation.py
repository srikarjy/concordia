"""Executable release gates for campaign provenance and replay safety."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from concordia.campaigns.recommendations import SelectionCandidate, select_candidates
from concordia.campaigns.schema import (
    AssayStatus,
    CampaignAuditEvent,
    CampaignModelRun,
    DatasetSnapshot,
    Measurement,
    Recommendation,
)

ALLOWED_EXTERNAL_PROVIDERS = frozenset(
    {
        "nvidia-boltz",
        "nvidia-rfdiffusion",
        "nvidia-proteinmpnn",
        "nvidia-bionemo-framework",
        "nvidia-bionemo-inference",
    }
)


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class ValidationReport:
    checks: tuple[ValidationCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


@dataclass(frozen=True)
class CampaignValidationReport:
    checks: tuple[ValidationCheck, ...]
    scientific_use_allowed: bool = False
    prospective_claim_allowed: bool = False

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def validate_campaign_round(
    measurements: tuple[Measurement, ...],
    model_runs: tuple[CampaignModelRun, ...],
    datasets: tuple[DatasetSnapshot, ...] = (),
    audit_events: tuple[CampaignAuditEvent, ...] = (),
) -> CampaignValidationReport:
    """Combine local release gates without promoting scientific validity."""
    checks: list[ValidationCheck] = [
        ValidationCheck(
            "release_inputs_present",
            bool(measurements or model_runs or datasets),
            "a release report requires at least one persisted assay or model record",
        )
    ]
    measurement_report = validate_measurement_semantics(measurements)
    checks.extend(
        ValidationCheck(f"assay.{check.name}", check.passed, check.reason)
        for check in measurement_report.checks
    )
    for run in model_runs:
        checks.extend(
            ValidationCheck(f"model.{run.model_run_id}.{check.name}", check.passed, check.reason)
            for check in validate_model_run_lineage(run).checks
        )
    for dataset in datasets:
        checks.append(
            ValidationCheck(
                f"dataset.{dataset.dataset_id}.digest",
                _is_sha256(dataset.dataset_digest),
                "frozen dataset identity is canonical",
            )
        )
        benchmark_recorded = any(
            event.action == "benchmark.completed"
            and event.resource_type == "dataset"
            and event.resource_id == dataset.dataset_id
            and _is_sha256(str(event.payload.get("benchmark_digest", "")))
            and _is_sha256(str(event.payload.get("artifact_digest", "")))
            for event in audit_events
        )
        checks.append(
            ValidationCheck(
                f"dataset.{dataset.dataset_id}.retrospective_benchmark",
                bool(benchmark_recorded),
                "a frozen dataset requires a content-addressed retrospective benchmark report",
            )
        )
    checks.append(
        ValidationCheck(
            "scientific_boundary",
            True,
            "computational validation does not establish experimental or clinical evidence",
        )
    )
    return CampaignValidationReport(tuple(checks))


def validate_model_run_lineage(run: CampaignModelRun) -> ValidationReport:
    checks = (
        ValidationCheck(
            "input_digest",
            _is_sha256(run.input_digest),
            "input artifact identity is canonical",
        ),
        ValidationCheck(
            "parameter_digest",
            _is_sha256(run.parameter_digest),
            "parameter identity is canonical",
        ),
        ValidationCheck(
            "provider_allowlist",
            run.provider in ALLOWED_EXTERNAL_PROVIDERS
            or run.provider in {"concordia-protein-baseline", "concordia-measured-stability"},
            "provider is explicitly registered or approved",
        ),
        ValidationCheck(
            "completed_output",
            run.status.value != "completed" or bool(run.output_artifact_digests),
            "completed runs retain at least one output artifact",
        ),
        ValidationCheck(
            "scientific_gate",
            run.scientific_use_allowed is False,
            "model execution cannot self-promote to scientific evidence",
        ),
    )
    return ValidationReport(checks)


def validate_measurement_semantics(measurements: tuple[Measurement, ...]) -> ValidationReport:
    checks = []
    for measurement in measurements:
        value_required = measurement.status in {
            AssayStatus.MEASURED,
            AssayStatus.BELOW_DETECTION,
            AssayStatus.ABOVE_DETECTION,
        }
        checks.append(
            ValidationCheck(
                f"measurement:{measurement.measurement_id}",
                (measurement.value is not None) if value_required else True,
                "censored/measured values are distinguishable from failed or planned assays",
            )
        )
    return ValidationReport(tuple(checks))


def validate_recommendation_replay(
    recommendation: Recommendation,
    candidates: tuple[SelectionCandidate, ...],
    *,
    batch_size: int,
    seed: int,
) -> ValidationReport:
    try:
        replay = select_candidates(
            candidates,
            policy=recommendation.policy,
            batch_size=batch_size,
            seed=seed,
        )
        matches = replay.candidate_ids == recommendation.candidate_ids
        reason = "recommendation matches deterministic replay" if matches else "replay differs"
    except (ValueError, TypeError) as error:
        matches = False
        reason = f"replay failed: {type(error).__name__}"
    return ValidationReport(
        (
            ValidationCheck("recommendation_replay", matches, reason),
            ValidationCheck(
                "recommendation_scientific_gate",
                recommendation.status != "validated",
                "recommendation status cannot imply scientific validation",
            ),
        )
    )


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        return hashlib.sha256(bytes.fromhex(value)).digest() is not None
    except ValueError:
        return False


__all__ = [
    "ALLOWED_EXTERNAL_PROVIDERS",
    "ValidationCheck",
    "CampaignValidationReport",
    "ValidationReport",
    "validate_campaign_round",
    "validate_measurement_semantics",
    "validate_model_run_lineage",
    "validate_recommendation_replay",
]
