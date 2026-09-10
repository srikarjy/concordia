"""Deterministic qualification metrics and selection for local scientist models."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from concordia.scientist.contracts import ScientistExecutionRecord


class QualificationCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    criteria_version: str = "genomic-scientist-qualification-v1"
    minimum_json_valid_rate: float = Field(default=1.0, ge=0, le=1)
    minimum_tool_request_valid_rate: float = Field(default=0.5, ge=0, le=1)
    minimum_claim_schema_valid_rate: float = Field(default=1.0, ge=0, le=1)
    minimum_evidence_reference_correctness: float = Field(default=1.0, ge=0, le=1)
    minimum_repeated_run_stability: float = Field(default=0.5, ge=0, le=1)


class ModelQualification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_identity: str
    checkpoint_digest: str | None
    repetitions: int = Field(ge=1)
    json_valid_rate: float = Field(ge=0, le=1)
    tool_request_valid_rate: float = Field(ge=0, le=1)
    claim_schema_valid_rate: float = Field(ge=0, le=1)
    evidence_reference_correctness: float = Field(ge=0, le=1)
    repeated_run_stability: float = Field(ge=0, le=1)
    mean_latency_seconds: float | None = Field(default=None, ge=0)
    peak_memory_bytes: int | None = Field(default=None, ge=0)
    mean_input_tokens: float | None = Field(default=None, ge=0)
    mean_output_tokens: float | None = Field(default=None, ge=0)
    qualified: bool
    selection_score: float = Field(ge=0, le=1)
    execution_artifact_digests: tuple[str, ...]


class QualificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    criteria: QualificationCriteria
    candidates: tuple[ModelQualification, ...]
    selected_model: str | None
    selection_rationale: str
    scientific_use_allowed: Literal[False] = False


def qualify_records(
    records: Sequence[ScientistExecutionRecord],
    criteria: QualificationCriteria | None = None,
) -> ModelQualification:
    if not records:
        raise ValueError("qualification requires at least one execution record")
    declared = criteria or QualificationCriteria()
    model_identity = records[0].model_identity
    if any(record.model_identity != model_identity for record in records):
        raise ValueError("qualification records must belong to one model")
    repetitions = len(records)
    turns = [turn for record in records for turn in record.turns]
    json_valid = []
    for turn in turns:
        try:
            json.loads(turn.raw_response or "")
            json_valid.append(True)
        except (ValueError, TypeError):
            json_valid.append(False)
    json_valid_rate = sum(json_valid) / len(json_valid) if json_valid else 0.0
    tool_valid_runs = sum(
        any(turn.tool_succeeded is True for turn in record.turns)
        for record in records
    )
    tool_request_valid_rate = tool_valid_runs / repetitions
    claim_schema_valid = sum(record.final_response is not None for record in records)
    claim_schema_valid_rate = claim_schema_valid / repetitions
    evidence_correct = sum(
        record.final_response is not None
        and bool(record.final_response.claims)
        and not record.reference_errors
        for record in records
    )
    evidence_reference_correctness = evidence_correct / repetitions
    fingerprints = [
        json.dumps(
            record.final_response.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        if record.final_response is not None
        else f"failure:{record.status}:{record.terminal_reason}"
        for record in records
    ]
    successful_fingerprints = [
        fingerprint for record, fingerprint in zip(records, fingerprints, strict=True)
        if record.final_response is not None and not record.reference_errors
    ]
    repeated_run_stability = (
        max(Counter(successful_fingerprints).values()) / repetitions
        if successful_fingerprints else 0.0
    )
    responses = [
        turn.model_response
        for record in records
        for turn in record.turns
        if turn.model_response is not None
    ]
    latencies = [response.elapsed_seconds for response in responses]
    memories = [
        response.memory_bytes
        for response in responses
        if response.memory_bytes is not None
    ]
    input_tokens = [
        response.input_tokens
        for response in responses
        if response.input_tokens is not None
    ]
    output_tokens = [
        response.output_tokens
        for response in responses
        if response.output_tokens is not None
    ]
    qualified = (
        json_valid_rate >= declared.minimum_json_valid_rate
        and tool_request_valid_rate >= declared.minimum_tool_request_valid_rate
        and claim_schema_valid_rate >= declared.minimum_claim_schema_valid_rate
        and evidence_reference_correctness
        >= declared.minimum_evidence_reference_correctness
        and repeated_run_stability >= declared.minimum_repeated_run_stability
    )
    score = (
        0.25 * json_valid_rate
        + 0.20 * tool_request_valid_rate
        + 0.25 * claim_schema_valid_rate
        + 0.20 * evidence_reference_correctness
        + 0.10 * repeated_run_stability
    )
    return ModelQualification(
        model_identity=model_identity,
        checkpoint_digest=records[0].checkpoint_digest,
        repetitions=repetitions,
        json_valid_rate=json_valid_rate,
        tool_request_valid_rate=tool_request_valid_rate,
        claim_schema_valid_rate=claim_schema_valid_rate,
        evidence_reference_correctness=evidence_reference_correctness,
        repeated_run_stability=repeated_run_stability,
        mean_latency_seconds=mean(latencies) if latencies else None,
        peak_memory_bytes=max(memories) if memories else None,
        mean_input_tokens=mean(input_tokens) if input_tokens else None,
        mean_output_tokens=mean(output_tokens) if output_tokens else None,
        qualified=qualified,
        selection_score=round(score, 10),
        execution_artifact_digests=tuple(
            record.artifact_digest
            for record in records
            if record.artifact_digest is not None
        ),
    )


def select_model(
    candidates: Sequence[ModelQualification],
    criteria: QualificationCriteria | None = None,
) -> QualificationReport:
    declared = criteria or QualificationCriteria()
    ordered = tuple(sorted(candidates, key=lambda item: item.model_identity))
    passing = [candidate for candidate in ordered if candidate.qualified]
    if not passing:
        return QualificationReport(
            criteria=declared,
            candidates=ordered,
            selected_model=None,
            selection_rationale="No candidate met every declared qualification threshold.",
        )
    selected = min(
        passing,
        key=lambda item: (
            -item.selection_score,
            item.mean_latency_seconds if item.mean_latency_seconds is not None else float("inf"),
            item.peak_memory_bytes if item.peak_memory_bytes is not None else 2**63,
            item.model_identity,
        ),
    )
    return QualificationReport(
        criteria=declared,
        candidates=ordered,
        selected_model=selected.model_identity,
        selection_rationale=(
            "Selected among threshold-passing candidates by highest documented quality "
            "score, then lower latency, lower measured memory, and model name."
        ),
    )
