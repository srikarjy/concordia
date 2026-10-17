"""Redacted campaign report manifests for figures and evidence review."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from concordia.campaigns.schema import (
    Campaign,
    CampaignAuditEvent,
    CampaignModelRun,
    Candidate,
    DatasetSnapshot,
    EvidenceClaim,
    Recommendation,
)


def build_report_manifest(
    campaign: Campaign,
    *,
    candidates: tuple[Candidate, ...] = (),
    datasets: tuple[DatasetSnapshot, ...] = (),
    model_runs: tuple[CampaignModelRun, ...] = (),
    recommendations: tuple[Recommendation, ...] = (),
    evidence_claims: tuple[EvidenceClaim, ...] = (),
    audit_events: tuple[CampaignAuditEvent, ...] = (),
    generated_at: datetime,
) -> dict[str, Any]:
    """Build a stable report manifest suitable for BioRender figure assembly.

    The manifest contains sequence hashes and artifact references, never raw
    sequences. It is a reporting input, not a scientific-use promotion gate.
    """
    payload: dict[str, Any] = {
        "schema_version": 1,
        "format": "concordia-biorender-manifest-v1",
        "campaign": {
            "campaign_id": campaign.campaign_id,
            "organization_id": campaign.organization_id,
            "title": campaign.title,
            "objective": campaign.objective,
            "target_sequence_hash": _sha256(campaign.target_sequence),
        },
        "lineage": {
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "round_id": candidate.round_id,
                    "sequence_hash": candidate.sequence_hash,
                    "parent_ids": candidate.parent_ids,
                    "source": candidate.source,
                }
                for candidate in candidates
            ],
            "datasets": [
                {
                    "dataset_id": dataset.dataset_id,
                    "round_id": dataset.round_id,
                    "dataset_digest": dataset.dataset_digest,
                    "row_count": dataset.row_count,
                    "measurement_count": len(dataset.measurement_ids),
                    "transformation_policy": dataset.transformation_policy,
                }
                for dataset in datasets
            ],
            "model_runs": [
                {
                    "model_run_id": run.model_run_id,
                    "provider": run.provider,
                    "model": run.model,
                    "model_version": run.model_version,
                    "status": run.status,
                    "input_artifact_digests": run.input_artifact_digests,
                    "output_artifact_digests": run.output_artifact_digests,
                    "input_digest": run.input_digest,
                    "parameter_digest": run.parameter_digest,
                    "scientific_use_allowed": run.scientific_use_allowed,
                }
                for run in model_runs
            ],
            "recommendations": [
                {
                    "recommendation_id": recommendation.recommendation_id,
                    "round_id": recommendation.round_id,
                    "candidate_ids": recommendation.candidate_ids,
                    "policy": recommendation.policy,
                    "evidence_snapshot": recommendation.evidence_snapshot,
                    "status": recommendation.status,
                }
                for recommendation in recommendations
            ],
            "evidence_claims": [
                {
                    "claim_id": claim.claim_id,
                    "subject_id": claim.subject_id,
                    "claim_type": claim.claim_type,
                    "verification_status": claim.verification_status,
                    "evidence_artifact_digests": claim.evidence_artifact_digests,
                    "scientific_use_allowed": claim.scientific_use_allowed,
                }
                for claim in evidence_claims
            ],
            "audit_events": [
                {
                    "event_id": event.event_id,
                    "actor": event.actor,
                    "action": event.action,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
                for event in audit_events
            ],
        },
        "figures": [
            {
                "figure_id": "campaign-lineage-overview",
                "kind": "lineage_and_measurements",
                "biorender_editable": True,
                "data_refs": ["lineage.candidates", "lineage.datasets", "lineage.recommendations"],
            },
            {
                "figure_id": "model-run-provenance",
                "kind": "model_run_artifact_graph",
                "biorender_editable": True,
                "data_refs": ["lineage.model_runs"],
            },
        ],
        "generated_at": generated_at.isoformat(),
        "scientific_use_allowed": False,
    }
    payload["manifest_digest"] = _manifest_digest(payload)
    return payload


def verify_report_manifest(manifest: Mapping[str, Any]) -> bool:
    """Verify a previously exported manifest without contacting the campaign store."""
    recorded_digest = manifest.get("manifest_digest")
    if not isinstance(recorded_digest, str) or len(recorded_digest) != 64:
        return False
    unsigned = dict(manifest)
    unsigned.pop("manifest_digest", None)
    return hmac.compare_digest(recorded_digest, _manifest_digest(unsigned))


def _manifest_digest(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["build_report_manifest", "verify_report_manifest"]
