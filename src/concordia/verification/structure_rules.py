"""Deterministic rules that turn measured structure signals into evidence assessments.

The rules see numbers, never structures: measuring clashes, buried surface or
interface agreement needs a structure library, and that happens in the scripts
that produce ``StructureMeasurements``. Keeping the rules on plain numbers keeps
them versioned, testable and free of heavy dependencies.

What a single prediction can and cannot say about itself. On the nine
post-cutoff antibody complexes in ``reports/``, six of the seven incorrect poses
bound through the variable domain with normal buried surface and few clashes,
so physical plausibility rejected one of seven. It is a floor, not a test of
correctness. The discriminating families need further, independent predictions:
agreement between samples or models, and a counterfactual in which the predicted
paratope is perturbed and the interface is expected to move.

Model self-reported confidence is recorded but never becomes evidence: it is not
independent of the claim it would support.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field

from concordia.genomes.schema import EvidenceFamily
from concordia.verification.cross import (
    ClaimRequest,
    EvidenceRecord,
    Frozen,
    ProvenanceArtifact,
    StructureScope,
    VerificationPolicy,
    VerificationResult,
    verify_claim,
)

RULE_PACK_VERSION = "structure-rules-v1"

Assessment = Literal["supports", "contradicts", "null", "missing"]


class PlausibilityThresholds(Frozen):
    """Generic floors for an antibody-antigen interface, not tuned to any benchmark."""

    max_clashes: int = Field(default=10, ge=0)
    min_variable_domain_fraction: float = Field(default=0.9, ge=0, le=1)
    min_buried_surface: float = Field(default=800.0, ge=0)
    max_buried_surface: float = Field(default=3500.0, gt=0)


class AgreementThresholds(Frozen):
    """Fraction of reference-prediction contacts reproduced by an independent prediction."""

    supports_at: float = Field(default=0.5, ge=0, le=1)
    contradicts_below: float = Field(default=0.2, ge=0, le=1)


class StructureMeasurements(Frozen):
    """Signals measured on one predicted complex; every field is optional evidence."""

    clash_count: int | None = Field(default=None, ge=0)
    variable_domain_fraction: float | None = Field(default=None, ge=0, le=1)
    buried_surface_area: float | None = Field(default=None, ge=0)
    sample_interface_agreement: float | None = Field(default=None, ge=0, le=1)
    second_model_interface_agreement: float | None = Field(default=None, ge=0, le=1)
    perturbed_paratope_interface_agreement: float | None = Field(default=None, ge=0, le=1)
    reference_dockq: float | None = Field(default=None, ge=0, le=1)
    self_reported_confidence: float | None = Field(default=None, ge=0, le=1)


def plausibility(
    measured: StructureMeasurements, limits: PlausibilityThresholds | None = None
) -> tuple[Assessment, tuple[str, ...]]:
    limits = limits or PlausibilityThresholds()
    failures: list[str] = []
    known = 0
    if measured.clash_count is not None:
        known += 1
        if measured.clash_count > limits.max_clashes:
            failures.append(f"{measured.clash_count} interface clashes")
    if measured.variable_domain_fraction is not None:
        known += 1
        if measured.variable_domain_fraction < limits.min_variable_domain_fraction:
            failures.append(
                f"only {measured.variable_domain_fraction:.0%} of antibody contacts are in the "
                "variable domain"
            )
    if measured.buried_surface_area is not None:
        known += 1
        if (
            not limits.min_buried_surface
            <= measured.buried_surface_area
            <= limits.max_buried_surface
        ):
            failures.append(f"buried surface {measured.buried_surface_area:.0f} A^2 out of range")
    if failures:
        return "contradicts", tuple(failures)
    if known == 0:
        return "missing", ("no physical measurements",)
    return "supports", ()


def agreement(value: float | None, limits: AgreementThresholds | None = None) -> Assessment:
    limits = limits or AgreementThresholds()
    if value is None:
        return "missing"
    if value >= limits.supports_at:
        return "supports"
    if value < limits.contradicts_below:
        return "contradicts"
    return "null"


def counterfactual(value: float | None, limits: AgreementThresholds | None = None) -> bool | None:
    """The interface should move when the predicted paratope is perturbed.

    ``value`` is how much of the original interface survives the perturbation. A
    pose that survives losing its own paratope was not using it.
    """

    limits = limits or AgreementThresholds()
    if value is None:
        return None
    return value < limits.contradicts_below


def evidence_records(
    measured: StructureMeasurements,
    scope: StructureScope,
    artifacts: dict[str, str],
    *,
    include_reference: bool = False,
) -> tuple[EvidenceRecord, ...]:
    """Build evidence records for the signals that were measured.

    ``artifacts`` maps each signal name to the digest of the provenance envelope
    that holds its measurement. ``include_reference`` adds DockQ against an
    experimental structure; leave it off when the verifier is being evaluated,
    because the reference is then the label, not evidence.
    """

    records: list[EvidenceRecord] = []

    def add(
        name: str,
        family: EvidenceFamily,
        method: str,
        group: str,
        assessment: Assessment,
        strength: float,
        passed: bool | None = None,
        critical: bool = False,
    ) -> None:
        if name not in artifacts:
            return
        records.append(
            EvidenceRecord(
                evidence_id=f"{scope.complex_id}:{name}",
                family=family,
                method=method,
                independence_group=group,
                artifact_digest=artifacts[name],
                scope=scope,
                assessment=assessment,
                strength=strength,
                critical=critical,
                counterfactual_passed=passed,
            )
        )

    physical, _ = plausibility(measured)
    if physical != "missing":
        # Below the default support threshold on purpose: plausibility rejected only one
        # of seven incorrect benchmark poses, so it may contradict a claim but cannot
        # carry one.
        add(
            "physical",
            EvidenceFamily.PHYSICAL_PLAUSIBILITY,
            "interface_geometry",
            "geometry",
            physical,
            0.6,
        )
    sample = agreement(measured.sample_interface_agreement)
    if sample != "missing":
        # Samples share weights and inputs, so agreement between them is weak evidence.
        add(
            "samples",
            EvidenceFamily.CROSS_MODEL,
            "diffusion_sample_consensus",
            "same-model",
            sample,
            0.5,
        )
    second = agreement(measured.second_model_interface_agreement)
    if second != "missing":
        # An independent model placing the antigen elsewhere is a real conflict, so it
        # is critical: the verifier otherwise lets any support outrank a contradiction.
        add(
            "second_model",
            EvidenceFamily.CROSS_MODEL,
            "independent_model_agreement",
            "second-model",
            second,
            0.9,
            critical=second == "contradicts",
        )
    passed = counterfactual(measured.perturbed_paratope_interface_agreement)
    if passed is not None:
        add(
            "counterfactual",
            EvidenceFamily.COUNTERFACTUAL,
            "paratope_perturbation",
            "perturbation",
            "supports" if passed else "contradicts",
            0.9,
            passed=passed,
        )
    if include_reference and measured.reference_dockq is not None:
        correct = measured.reference_dockq >= 0.23
        add(
            "reference",
            EvidenceFamily.STRUCTURAL_REFERENCE,
            "dockq",
            "experimental-structure",
            "supports" if correct else "contradicts",
            1.0,
            critical=not correct,
        )
    return tuple(records)


class _MemoryArtifactStore:
    """In-memory content-addressed store, so verification needs no filesystem.

    ``verify_measurements`` synthesises throwaway provenance envelopes purely so
    the ordinary verifier can walk them. Nothing here outlives the call.
    """

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put_json(self, value: object) -> str:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        digest = hashlib.sha256(payload).hexdigest()
        self._blobs[digest] = payload
        return digest

    def get_bytes(self, digest: str) -> bytes:
        return self._blobs[digest]


SIGNAL_NAMES: tuple[str, ...] = (
    "physical",
    "samples",
    "second_model",
    "counterfactual",
    "reference",
)


def verify_measurements(
    measured: StructureMeasurements,
    scope: StructureScope,
    *,
    claim_text: str,
    include_reference: bool = False,
    policy: VerificationPolicy | None = None,
) -> VerificationResult:
    """Verify measured signals directly, persisting nothing.

    The caller supplies measurements and a scope; the provenance envelopes the
    verifier expects are built in memory. ``include_reference`` admits DockQ
    against an experimental structure and must stay off whenever the verifier
    itself is being evaluated, because the reference is then the label rather
    than evidence.
    """

    store = _MemoryArtifactStore()
    description = f"structure measurements for {scope.complex_id}"

    def envelope(
        kind: Literal["sequence", "evidence"],
        payload: dict[str, object],
        parents: tuple[str, ...] = (),
    ) -> str:
        return store.put_json(
            ProvenanceArtifact(
                kind=kind,
                payload_digest=store.put_json(payload),
                dependencies=parents,
                execution_mode="recorded_real",
                scientific_use_allowed=True,
                source=description,
                producing_tool=f"structure_rules/{RULE_PACK_VERSION}",
            ).model_dump(mode="json")
        )

    source = envelope("sequence", {"complex_id": scope.complex_id})
    measured_json = measured.model_dump(mode="json", exclude_none=True)
    artifacts = {
        name: envelope("evidence", {"signal": name, **measured_json}, (source,))
        for name in SIGNAL_NAMES
    }
    claim = ClaimRequest(
        claim_id=scope.complex_id,
        text=claim_text,
        scope=scope,
        source_sequence=source,
        evidence=evidence_records(
            measured, scope, artifacts, include_reference=include_reference
        ),
    )
    return verify_claim(claim, store, policy)
