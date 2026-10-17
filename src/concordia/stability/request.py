"""Language-independent typed entry point for the measured-stability workflow.

The command-line form treats comma-separated substitutions as a candidate set:
``A13Q,K6Q,L52Y`` means three single-mutant candidates. A colon-separated item,
such as ``A13Q:K6Q``, is one multi-mutant candidate and is refused by the
singles-only constraint. The engine, rather than this parser, owns all scientific
decisions and reads the frozen manifest and ranker artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from concordia.events.sqlite import SQLiteEventLedger
from concordia.stability.measured import (
    UNCERTAINTY_PATH,
    MeasuredCandidate,
    MeasuredStabilityEngine,
    render_recommendation,
)
from concordia.storage.content import ContentAddressedStore

_MUTATION = re.compile(r"^(?P<from>[A-Z])(?P<position>[0-9]+)(?P<to>[A-Z])$")


class MutationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_aa: str = Field(alias="from")
    position: int
    to_aa: str

    @field_validator("from_aa", "to_aa")
    @classmethod
    def _one_letter(cls, value: str) -> str:
        if value not in "ACDEFGHIKLMNPQRSTVWY":
            raise ValueError("mutation amino acids must be standard one-letter codes")
        return value


class TypedStabilityRequest(BaseModel):
    """A typed request containing one or more candidate mutation groups."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str
    mutation_groups: tuple[tuple[MutationSpec, ...], ...] = Field(min_length=1)

    @classmethod
    def from_cli(cls, domain: str, raw: str) -> TypedStabilityRequest:
        if not raw.strip():
            raise ValueError("--mutations must contain at least one substitution")
        groups: list[tuple[MutationSpec, ...]] = []
        for group_text in raw.split(","):
            mutations: list[MutationSpec] = []
            for token in group_text.split(":"):
                match = _MUTATION.fullmatch(token.strip())
                if match is None:
                    raise ValueError(f"invalid mutation token: {token}")
                mutations.append(
                    MutationSpec.model_validate(
                        {
                            "from": str(match.group("from")),
                            "position": int(match.group("position")),
                            "to_aa": str(match.group("to")),
                        }
                    )
                )
            groups.append(tuple(mutations))
        return cls(domain=domain, mutation_groups=tuple(groups))


def candidates_for_request(
    engine: MeasuredStabilityEngine, request: TypedStabilityRequest
) -> list[MeasuredCandidate]:
    """Resolve typed substitutions against the frozen manifest without scoring."""
    selected_domain = str(engine.manifest["selection"]["selected_domain_id"])
    if request.domain not in {selected_domain, selected_domain.removesuffix(".pdb")}:
        raise ValueError(f"typed request domain is not the frozen domain: {request.domain}")
    mutable = set(range(1, int(engine.manifest["selection"]["length"]) + 1))
    hard_positions = set(engine.hard_protected)
    candidates: list[MeasuredCandidate] = []
    for group in request.mutation_groups:
        if not group:
            raise ValueError("mutation groups cannot be empty")
        for mutation in group:
            if mutation.position not in mutable:
                raise ValueError(
                    f"position {mutation.position} is outside the manifest mutable range"
                )
        first = group[0]
        tokens = [
            f"{mutation.from_aa}{mutation.position}{mutation.to_aa}" for mutation in group
        ]
        variant_id = f"{selected_domain}_{':'.join(tokens)}"
        if len(group) == 1 and first.position not in hard_positions:
            row = engine.rows.get(variant_id)
            if row is None:
                raise ValueError(f"mutation is not in the frozen measured table: {variant_id}")
            candidates.append(row)
        else:
            candidates.append(
                MeasuredCandidate(
                    variant_id,
                    first.position,
                    first.to_aa,
                    mutation_count=len(group),
                )
            )
    return candidates


def run_typed_request(
    request: TypedStabilityRequest,
    *,
    state_root: Path = Path(".concordia/typed-stability"),
    engine: MeasuredStabilityEngine | None = None,
) -> dict[str, Any]:
    """Run constraints, scoring, ranking, ledgering, and artifact creation locally."""
    active_engine = engine or MeasuredStabilityEngine()
    candidates = candidates_for_request(active_engine, request)
    report = active_engine.rank(candidates)
    uncertainty = json.loads(UNCERTAINTY_PATH.read_text(encoding="utf-8"))
    holdout_summary = uncertainty["holdout"]
    interval_quantile = float(holdout_summary["normalized_quantile"])
    label_range = [
        float(value) for value in holdout_summary["normalized"]["label_range_kcal_mol"]
    ]
    for item in report["candidates"]:
        mean = float(item["mean_prediction_ddg_kcal_higher_is_more_stable"])
        sigma = float(item["ensemble_sigma"])
        item["interval_90_kcal_mol"] = {
            "lower": mean - interval_quantile * sigma,
            "upper": mean + interval_quantile * sigma,
            "width": 2 * interval_quantile * sigma,
            "method": "normalized split conformal",
        }
    if report["candidates"]:
        top = report["candidates"][0]
        slots: dict[str, str | float | int | None] = {
            "variant_id": top["candidate"]["variant_id"],
            "score": f"{top['mean_prediction_ddg_kcal_higher_is_more_stable']:.4f}",
            "sigma": f"{top['ensemble_sigma']:.4f}",
        }
        prose = render_recommendation(
            "Ranked candidate {variant_id}: predicted stability {score} kcal/mol; "
            "uncertainty sigma {sigma} kcal/mol.",
            slots,
        )
    else:
        slots = {}
        prose = ""
    report = {
        **report,
        "typed_request": request.model_dump(mode="json"),
        "scope_statement": (
            "One frozen domain and one folding-stability property; in-silico only. "
            "Intervals are too wide to act on. Hard-protected, T2, and multi-mutant "
            "requests are refused; unseen positions and buried-core residues are soft flags."
        ),
        "ollama_used": False,
        "holdout_used": False,
        "slot_values": slots,
        "rendered_prose": prose,
        "structure": {
            "path": "structure/1IGV.pdb",
            "source": "Tsuboyama bundled AlphaFold model; not an experimental structure",
            "protected_residues": [
                dict(item)
                for item in active_engine.manifest["selection"]["hard_protected_residues"]
            ],
            "soft_buried_positions": sorted(
                position
                for position, rsa in active_engine.soft_rsa.items()
                if rsa < 0.15
            ),
        },
        "interval_context": {
            "nominal_coverage": 0.90,
            "holdout_picp": float(holdout_summary["normalized"]["picp"]),
            "label_range_kcal_mol": label_range,
            "mean_width_kcal_mol": float(holdout_summary["normalized"]["mean_width_kcal_mol"]),
            "range_fraction": float(
                holdout_summary["normalized"]["mean_width_kcal_mol"]
                / (label_range[1] - label_range[0])
            ),
            "ranking_use": "refusal-only; not an acquisition or ranking term",
        },
        "scope_metrics": {
            "thermompnn_rank_average_top10_recall_modulo": "0.336 +/- 0.060",
            "thermompnn_rank_average_top10_recall_contiguous": "0.358 +/- 0.023",
            "thermompnn_training_membership": "ABSENT",
        },
    }
    state_root.mkdir(parents=True, exist_ok=True)
    artifacts = ContentAddressedStore(state_root / "artifacts")
    artifact_digest = artifacts.put_json(report)
    ledger = SQLiteEventLedger(state_root / "events.sqlite3")
    request_digest = hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    run_id = f"typed-stability-{uuid.uuid4().hex}"
    ledger.create_run(
        run_id=run_id,
        idempotency_key=run_id,
        command_digest=request_digest,
        payload={
            "typed_request": request.model_dump(mode="json"),
            "artifact_digest": artifact_digest,
        },
        event_id=f"{run_id}:created",
    )
    ledger.append(
        run_id,
        "STABILITY_RESULT",
        {"artifact_digest": artifact_digest, "ranker": report["ranker"], "holdout_used": False},
        expected_sequence=1,
        event_id=f"{run_id}:result",
    )
    report["artifact_digest"] = artifact_digest
    report["run_id"] = run_id
    report["ledger_intact"] = ledger.verify_chain(run_id).intact
    return report


__all__ = [
    "MutationSpec",
    "TypedStabilityRequest",
    "candidates_for_request",
    "run_typed_request",
]
