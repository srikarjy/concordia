"""Deterministic comparison of structured scientist responses."""

from __future__ import annotations

from typing import Any

from concordia.scientist.schema import ScientificClaim, ScientistResponse


def _claim_map(response: ScientistResponse) -> dict[tuple[str, str], ScientificClaim]:
    result: dict[tuple[str, str], ScientificClaim] = {}
    for claim in response.claims:
        key = (claim.claim_key, claim.claim_type)
        if key in result:
            raise ValueError(f"Duplicate claim key/type: {key}")
        result[key] = claim
    return result


def compare_responses(
    control: ScientistResponse, intervention: ScientistResponse
) -> dict[str, Any]:
    """Compare claims by declared key/type; no semantic reasoning is performed."""
    control_map = _claim_map(control)
    intervention_map = _claim_map(intervention)
    control_keys = set(control_map)
    intervention_keys = set(intervention_map)
    matched = sorted(control_keys & intervention_keys)
    retained = sorted(control_keys & intervention_keys)
    removed = sorted(control_keys - intervention_keys)
    added = sorted(intervention_keys - control_keys)
    confidence_deltas = {
        f"{key[0]}::{key[1]}": intervention_map[key].confidence - control_map[key].confidence
        for key in matched
    }
    evidence_reference_changed = {
        f"{key[0]}::{key[1]}": sorted(control_map[key].evidence_references)
        != sorted(intervention_map[key].evidence_references)
        for key in matched
    }
    return {
        "control_claim_count": len(control_map),
        "intervention_claim_count": len(intervention_map),
        "retained_claims": [f"{key[0]}::{key[1]}" for key in retained],
        "removed_claims": [f"{key[0]}::{key[1]}" for key in removed],
        "added_claims": [f"{key[0]}::{key[1]}" for key in added],
        "claim_retention_rate": len(retained) / len(control_map) if control_map else None,
        "confidence_deltas": confidence_deltas,
        "evidence_reference_changed": evidence_reference_changed,
    }
