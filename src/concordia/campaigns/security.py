"""Organization-scoped campaign authorization and secret rotation primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class OrganizationRole(StrEnum):
    OWNER = "owner"
    SCIENTIST = "scientist"
    OPERATOR = "operator"
    VIEWER = "viewer"


class CampaignAction(StrEnum):
    READ = "read"
    EDIT_PROTOCOL = "edit_protocol"
    WRITE_ASSAY = "write_assay"
    RUN_MODEL = "run_model"
    VERIFY_EVIDENCE = "verify_evidence"
    MANAGE_ACCESS = "manage_access"


ROLE_ACTIONS: dict[OrganizationRole, frozenset[CampaignAction]] = {
    OrganizationRole.OWNER: frozenset(CampaignAction),
    OrganizationRole.SCIENTIST: frozenset(
        {
            CampaignAction.READ,
            CampaignAction.EDIT_PROTOCOL,
            CampaignAction.WRITE_ASSAY,
            CampaignAction.RUN_MODEL,
            CampaignAction.VERIFY_EVIDENCE,
        }
    ),
    OrganizationRole.OPERATOR: frozenset(
        {CampaignAction.READ, CampaignAction.WRITE_ASSAY, CampaignAction.RUN_MODEL}
    ),
    OrganizationRole.VIEWER: frozenset({CampaignAction.READ}),
}


@dataclass(frozen=True)
class CampaignPrincipal:
    principal_id: str
    organization_id: str
    role: OrganizationRole


@dataclass(frozen=True)
class SecretRecord:
    secret_id: str
    digest: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


def require_action(principal: CampaignPrincipal, action: CampaignAction) -> None:
    if action not in ROLE_ACTIONS[principal.role]:
        raise PermissionError(f"role {principal.role.value} cannot perform {action.value}")


def rotate_secret(
    secret_id: str,
    *,
    now: datetime | None = None,
    lifetime: timedelta | None = None,
) -> tuple[str, SecretRecord]:
    """Create a one-time-returned secret and a non-sensitive persisted record."""
    if not secret_id:
        raise ValueError("secret_id is required")
    created_at = now or datetime.now(UTC)
    if lifetime is not None and lifetime <= timedelta(0):
        raise ValueError("secret lifetime must be positive")
    raw_secret = secrets.token_urlsafe(32)
    record = SecretRecord(
        secret_id=secret_id,
        digest=hashlib.sha256(raw_secret.encode()).hexdigest(),
        created_at=created_at,
        expires_at=created_at + lifetime if lifetime else None,
        revoked_at=None,
    )
    return raw_secret, record


def verify_secret(record: SecretRecord, raw_secret: str, *, now: datetime | None = None) -> bool:
    if not raw_secret or record.revoked_at is not None:
        return False
    current = now or datetime.now(UTC)
    if record.expires_at is not None and current >= record.expires_at:
        return False
    candidate_digest = hashlib.sha256(raw_secret.encode()).hexdigest()
    return hmac.compare_digest(record.digest, candidate_digest)


__all__ = [
    "CampaignAction",
    "CampaignPrincipal",
    "OrganizationRole",
    "ROLE_ACTIONS",
    "SecretRecord",
    "require_action",
    "rotate_secret",
    "verify_secret",
]
