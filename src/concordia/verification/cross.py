"""Deterministic, artifact-checked evidence-family verification."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from concordia.genomes.schema import EvidenceFamily

Digest = str


class ArtifactReader(Protocol):
    def get_bytes(self, digest: str) -> bytes: ...


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1


class Scope(Frozen):
    assembly: str = Field(min_length=1)
    chromosome: str = Field(min_length=1)
    strand: Literal["+", "-"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    coordinate_convention: Literal["zero_based_half_open"] = "zero_based_half_open"
    model_checkpoint: str = Field(min_length=1)
    scoring_target: str = Field(min_length=1)
    assay: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> Scope:
        if self.end <= self.start:
            raise ValueError("window must have positive length")
        return self


class ProvenanceArtifact(Frozen):
    """Envelope created at ingestion; dependencies include every consumed artifact."""

    kind: Literal["sequence", "model", "annotation", "literature", "evidence", "claim"]
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependencies: tuple[str, ...] = ()
    execution_mode: Literal["real", "fixture", "synthetic", "recorded_real"]
    scientific_use_allowed: bool = False
    source: str = Field(min_length=1)
    producing_tool: str = Field(min_length=1)

    @model_validator(mode="after")
    def eligibility(self) -> ProvenanceArtifact:
        if self.execution_mode in {"fixture", "synthetic"} and self.scientific_use_allowed:
            raise ValueError("fixture and synthetic artifacts cannot permit scientific use")
        return self


class EvidenceRecord(Frozen):
    evidence_id: str = Field(min_length=1)
    family: EvidenceFamily
    method: str = Field(min_length=1)
    independence_group: str = Field(min_length=1)
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: Scope
    assessment: Literal["supports", "contradicts", "null", "missing"]
    strength: float = Field(ge=0, le=1)
    critical: bool = False
    counterfactual_passed: bool | None = None

    @model_validator(mode="after")
    def counterfactual_family(self) -> EvidenceRecord:
        if self.method in {"in_silico_mutagenesis", "sequence_perturbation", "mutational_scan"}:
            if self.family != EvidenceFamily.COUNTERFACTUAL:
                raise ValueError("perturbation methods belong to the counterfactual family")
        if self.family != EvidenceFamily.COUNTERFACTUAL and self.counterfactual_passed is not None:
            raise ValueError("counterfactual checks require the counterfactual family")
        return self


class ClaimRequest(Frozen):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    scope: Scope
    source_sequence: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[EvidenceRecord, ...]

    @model_validator(mode="after")
    def unique(self) -> ClaimRequest:
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence identifiers")
        return self


class SupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


class VerificationPolicy(Frozen):
    version: Literal["independent-evidence-v1"] = "independent-evidence-v1"
    minimum_families: int = Field(default=2, ge=2, le=5)
    minimum_strength: float = Field(default=0.75, ge=0, le=1)
    max_provenance_nodes: int = Field(default=1000, ge=1, le=10000)


class EvidenceCheck(Frozen):
    evidence_id: str
    family: EvidenceFamily
    assessment: str
    valid: bool
    source_path: tuple[str, ...] = ()
    artifacts_checked: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class VerificationResult(Frozen):
    claim_id: str
    status: SupportStatus
    policy: VerificationPolicy
    supporting_families: tuple[EvidenceFamily, ...]
    contradicting_families: tuple[EvidenceFamily, ...]
    checks: tuple[EvidenceCheck, ...]
    reasons: tuple[str, ...]
    scientific_use_allowed: bool
    limitation: str = "Support is scoped evidence agreement; it is not experimental proof."


def check_provenance(
    reader: ArtifactReader,
    root: str,
    sequence: str,
    limit: int,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Check all dependency branches, not only a favorable shortest path."""
    checked: set[str] = set()
    active: set[str] = set()
    errors: set[str] = set()
    path: tuple[str, ...] = ()

    def visit(digest: str, ancestors: tuple[str, ...]) -> None:
        nonlocal path
        if digest in active:
            errors.add("cyclic provenance")
            return
        if digest in checked:
            return
        if len(checked) >= limit:
            errors.add("provenance budget exceeded")
            return
        checked.add(digest)
        active.add(digest)
        try:
            envelope = ProvenanceArtifact.model_validate_json(reader.get_bytes(digest))
            reader.get_bytes(envelope.payload_digest)
            if not envelope.scientific_use_allowed:
                errors.add("provenance contains evidence ineligible for scientific use")
            if digest == sequence:
                if envelope.kind != "sequence":
                    errors.add("source does not identify a sequence artifact")
                else:
                    path = (*ancestors, digest)
            if envelope.kind in {"claim", "evidence"} and not envelope.dependencies:
                errors.add("derived artifact lacks dependencies")
            for parent in sorted(envelope.dependencies):
                visit(parent, (*ancestors, digest))
        except (ValueError, OSError, RecursionError):
            errors.add(f"missing, corrupt, or invalid artifact: {digest}")
        finally:
            active.remove(digest)

    visit(root, ())
    if not path:
        errors.add("evidence has no path to the declared source sequence")
    return path, tuple(sorted(checked)), tuple(sorted(errors))


def verify_claim(
    claim: ClaimRequest,
    reader: ArtifactReader,
    policy: VerificationPolicy | None = None,
) -> VerificationResult:
    policy = policy or VerificationPolicy()
    checks: list[EvidenceCheck] = []
    supports: set[EvidenceFamily] = set()
    contradicts: set[EvidenceFamily] = set()
    groups: dict[EvidenceFamily, set[str]] = {}
    reasons: set[str] = set()
    counterfactual = False
    critical = False
    for evidence in sorted(claim.evidence, key=lambda value: value.evidence_id):
        path, artifacts, errors = check_provenance(
            reader, evidence.artifact_digest, claim.source_sequence, policy.max_provenance_nodes
        )
        item_reasons = list(errors)
        if evidence.scope != claim.scope:
            item_reasons.append("evidence lies outside the declared model, window, or assay scope")
        valid = not item_reasons
        checks.append(
            EvidenceCheck(
                evidence_id=evidence.evidence_id,
                family=evidence.family,
                assessment=evidence.assessment,
                valid=valid,
                source_path=path,
                artifacts_checked=artifacts,
                reasons=tuple(item_reasons),
            )
        )
        reasons.update(item_reasons)
        if evidence.assessment == "contradicts":
            contradicts.add(evidence.family)
            critical |= evidence.critical
        if (
            valid
            and evidence.assessment == "supports"
            and evidence.strength >= policy.minimum_strength
        ):
            supports.add(evidence.family)
            groups.setdefault(evidence.family, set()).add(evidence.independence_group)
            if evidence.family == EvidenceFamily.COUNTERFACTUAL:
                counterfactual |= evidence.counterfactual_passed is True
        if evidence.assessment == "missing":
            reasons.add("declared evidence is missing")

    # Maximum bipartite matching: one independence group cannot confirm two families.
    assigned: dict[str, EvidenceFamily] = {}

    def match(family: EvidenceFamily, seen: set[str]) -> bool:
        for group in sorted(groups[family]):
            if group in seen:
                continue
            seen.add(group)
            if group not in assigned or match(assigned[group], seen):
                assigned[group] = family
                return True
        return False

    independent = sum(match(family, set()) for family in sorted(groups))
    if not claim.evidence:
        status = SupportStatus.MISSING_EVIDENCE
        reasons.add("no evidence supplied")
    elif any(not check.valid for check in checks):
        status = SupportStatus.UNVERIFIABLE
    elif critical:
        status = SupportStatus.CONTRADICTED
        reasons.add("unresolved critical contradiction")
    elif counterfactual and independent >= policy.minimum_families and not reasons:
        status = SupportStatus.SUPPORTED
    elif supports:
        status = SupportStatus.PARTIALLY_SUPPORTED
    elif contradicts:
        status = SupportStatus.CONTRADICTED
    else:
        status = SupportStatus.MISSING_EVIDENCE
    if not counterfactual:
        reasons.add("required counterfactual check is absent or did not pass")
    if independent < policy.minimum_families:
        reasons.add("insufficient independent supporting evidence families")
    return VerificationResult(
        claim_id=claim.claim_id,
        status=status,
        policy=policy,
        supporting_families=tuple(sorted(supports)),
        contradicting_families=tuple(sorted(contradicts)),
        checks=tuple(checks),
        reasons=tuple(sorted(reasons)),
        scientific_use_allowed=status == SupportStatus.SUPPORTED,
    )


def verification_json(result: VerificationResult) -> str:
    return json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
