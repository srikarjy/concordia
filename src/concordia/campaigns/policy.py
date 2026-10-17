"""Export and retention policies for private campaign data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from concordia.campaigns.schema import Candidate
from concordia.campaigns.security import (
    CampaignAction,
    CampaignPrincipal,
    OrganizationRole,
    require_action,
)


@dataclass(frozen=True)
class ExportPolicy:
    allow_raw_sequences: bool = False
    raw_sequence_roles: frozenset[OrganizationRole] = frozenset({OrganizationRole.OWNER})
    require_purpose: bool = True


@dataclass(frozen=True)
class RetentionPolicy:
    artifact_days: int = 365
    audit_days: int = 730
    legal_hold: bool = False


@dataclass(frozen=True)
class RetentionDecision:
    eligible: bool
    reason: str


def export_candidates(
    candidates: tuple[Candidate, ...],
    principal: CampaignPrincipal,
    *,
    policy: ExportPolicy | None = None,
    include_raw_sequences: bool = False,
    purpose: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Export lineage metadata by default; raw sequences require owner approval."""
    policy = policy or ExportPolicy()
    require_action(principal, CampaignAction.READ)
    if include_raw_sequences:
        if not policy.allow_raw_sequences or principal.role not in policy.raw_sequence_roles:
            raise PermissionError("raw sequence export is not permitted for this principal")
        if policy.require_purpose and not purpose:
            raise PermissionError("raw sequence export requires a stated purpose")
    return tuple(
        {
            "candidate_id": candidate.candidate_id,
            "campaign_id": candidate.campaign_id,
            "round_id": candidate.round_id,
            "sequence_hash": candidate.sequence_hash,
            "parent_ids": candidate.parent_ids,
            "source": candidate.source,
            **({"sequence": candidate.sequence} if include_raw_sequences else {}),
        }
        for candidate in candidates
    )


def retention_decision(
    created_at: datetime,
    *,
    kind: str,
    policy: RetentionPolicy,
    now: datetime | None = None,
) -> RetentionDecision:
    if policy.legal_hold:
        return RetentionDecision(False, "legal hold blocks deletion")
    days = policy.artifact_days if kind == "artifact" else policy.audit_days
    if days < 1:
        raise ValueError("retention duration must be positive")
    current = now or datetime.now(UTC)
    eligible = current - created_at >= timedelta(days=days)
    return RetentionDecision(
        eligible, "retention window elapsed" if eligible else "retention window active"
    )


__all__ = [
    "ExportPolicy",
    "RetentionDecision",
    "RetentionPolicy",
    "export_candidates",
    "retention_decision",
]
