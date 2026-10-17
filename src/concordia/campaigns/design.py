"""Typed de novo binder-design planning and ranking contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BinderDesignPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    plan_id: str
    target_structure_digest: str = Field(min_length=64, max_length=64)
    contigs: str = Field(min_length=1, max_length=500)
    hotspot_residues: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    num_backbones: int = Field(default=8, ge=1, le=100)
    sequences_per_backbone: int = Field(default=8, ge=1, le=100)
    max_cofolds: int = Field(default=16, ge=1, le=100)
    min_iptm: float = Field(default=0.8, ge=0, le=1)
    min_plddt: float = Field(default=80, ge=0, le=100)
    max_self_consistency_rmsd: float = Field(default=2.0, gt=0, le=100)
    budget_units: float = Field(default=10, gt=0, le=100_000)
    scientific_use_allowed: bool = False


class DesignStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    provider: str
    model: str
    parameters: dict[str, Any]


class CampaignDesignRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    plan: BinderDesignPlan
    campaign_id: str
    round_id: str
    stages: tuple[DesignStageRequest, ...]
    created_at: str


class DesignEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    design_id: str
    backbone_artifact_digest: str = Field(min_length=64, max_length=64)
    sequence_artifact_digest: str = Field(min_length=64, max_length=64)
    complex_artifact_digest: str = Field(min_length=64, max_length=64)
    iptm: float = Field(ge=0, le=1)
    binder_plddt: float = Field(ge=0, le=100)
    self_consistency_rmsd: float = Field(ge=0)
    scientific_use_allowed: bool = False


class DesignRanking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    ranked_design_ids: tuple[str, ...]
    passing_design_ids: tuple[str, ...]
    success_rate: float = Field(ge=0, le=1)
    filters: dict[str, float]
    scientific_use_allowed: bool = False


def build_binder_design_plan(
    *,
    plan_id: str,
    target_structure_digest: str,
    contigs: str,
    hotspot_residues: tuple[str, ...] = (),
    num_backbones: int = 8,
    sequences_per_backbone: int = 8,
    max_cofolds: int = 16,
    budget_units: float = 10,
) -> BinderDesignPlan:
    if len(target_structure_digest) != 64:
        raise ValueError("target structure must be a SHA-256 artifact digest")
    return BinderDesignPlan(
        plan_id=plan_id,
        target_structure_digest=target_structure_digest,
        contigs=contigs,
        hotspot_residues=hotspot_residues,
        num_backbones=num_backbones,
        sequences_per_backbone=sequences_per_backbone,
        max_cofolds=max_cofolds,
        budget_units=budget_units,
    )


def stage_requests(plan: BinderDesignPlan) -> tuple[DesignStageRequest, ...]:
    """Return the allow-listed stage graph without making provider calls."""
    return (
        DesignStageRequest(
            stage="backbone_generation",
            provider="nvidia-rfdiffusion",
            model="rfdiffusion",
            parameters={
                "target_pdb_digest": plan.target_structure_digest,
                "contigs": plan.contigs,
                "hotspot_residues": plan.hotspot_residues,
                "num_backbones": plan.num_backbones,
            },
        ),
        DesignStageRequest(
            stage="inverse_folding",
            provider="nvidia-proteinmpnn",
            model="proteinmpnn",
            parameters={
                "sequences_per_backbone": plan.sequences_per_backbone,
                "input_stage": "backbone_generation",
            },
        ),
        DesignStageRequest(
            stage="complex_cofold",
            provider="nvidia-boltz",
            model="boltz",
            parameters={
                "max_cofolds": plan.max_cofolds,
                "input_stage": "inverse_folding",
            },
        ),
    )


def rank_designs(
    plan: BinderDesignPlan, evaluations: tuple[DesignEvaluation, ...]
) -> DesignRanking:
    if len({evaluation.design_id for evaluation in evaluations}) != len(evaluations):
        raise ValueError("design IDs must be unique")
    passing = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.iptm >= plan.min_iptm
        and evaluation.binder_plddt >= plan.min_plddt
        and evaluation.self_consistency_rmsd <= plan.max_self_consistency_rmsd
    )
    ranked = tuple(
        evaluation.design_id
        for evaluation in sorted(
            evaluations,
            key=lambda item: (
                item not in passing,
                -item.iptm,
                -item.binder_plddt,
                item.self_consistency_rmsd,
                item.design_id,
            ),
        )
    )
    return DesignRanking(
        plan_id=plan.plan_id,
        ranked_design_ids=ranked,
        passing_design_ids=tuple(evaluation.design_id for evaluation in passing),
        success_rate=len(passing) / len(evaluations) if evaluations else 0,
        filters={
            "min_iptm": plan.min_iptm,
            "min_plddt": plan.min_plddt,
            "max_self_consistency_rmsd": plan.max_self_consistency_rmsd,
        },
    )


__all__ = [
    "BinderDesignPlan",
    "CampaignDesignRecord",
    "DesignEvaluation",
    "DesignRanking",
    "DesignStageRequest",
    "build_binder_design_plan",
    "rank_designs",
    "stage_requests",
]
