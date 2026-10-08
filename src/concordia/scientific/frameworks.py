"""Scientific framework registry exposed by the workspace.

This is descriptive metadata rather than an execution plugin system. Each
entry states what a framework contributes, where it runs, and what evidence
boundary still applies.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScientificFramework(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: Literal["genome_model", "structure_model", "data", "orchestration", "visualization"]
    role: str = Field(min_length=1)
    integration: str = Field(min_length=1)
    execution_mode: str = Field(min_length=1)
    status: Literal["integrated", "boundary", "planned"]
    scientific_boundary: str = Field(min_length=1)
    official_url: str = Field(min_length=1)


FRAMEWORKS: tuple[ScientificFramework, ...] = (
    ScientificFramework(
        id="evo2", name="Evo 2", category="genome_model",
        role="DNA generation and frozen-protocol causal likelihood scoring",
        integration="NVIDIA hosted generation plus an isolated ZeroGPU/NIM-compatible forward boundary",  # noqa: E501
        execution_mode="real_hosted_generation_or_external_worker", status="integrated",
        scientific_boundary="Generation is never scientific evidence; forward output is eligible only after checkpoint, token-count, target, hash, and numerical checks pass.",  # noqa: E501
        official_url="https://github.com/ArcInstitute/evo2",
    ),
    ScientificFramework(
        id="boltz2", name="Boltz-2", category="structure_model",
        role="Protein, nucleic-acid, and ligand complex structure prediction",
        integration="NVIDIA Boltz-2 NIM with content-addressed request/response artifacts and experiment-DAG lineage",  # noqa: E501
        execution_mode="real_hosted_nim", status="integrated",
        scientific_boundary="Hosted predictions are computational outputs; single-sequence self-reference is not a real MSA and no structure is treated as validated biology.",  # noqa: E501
        official_url="https://docs.nvidia.com/nim/bionemo/boltz2/latest/api-reference.html",
    ),
    ScientificFramework(
        id="cellforge", name="CellForge-compatible tools", category="orchestration",
        role="Bounded, policy-checked scientific tool execution",
        integration="Local process-isolated adapter with registered tools and provenance events",
        execution_mode="local_fixture_or_external_runtime", status="integrated",
        scientific_boundary="The local adapter is not a hardened hostile-code sandbox and fixture outputs cannot support scientific claims.",  # noqa: E501
        official_url="https://github.com/ArcInstitute/cellforge",
    ),
    ScientificFramework(
        id="anndata-scanpy", name="AnnData / Scanpy", category="data",
        role="Single-cell data interchange and analysis context for the separate virtual-cell track",  # noqa: E501
        integration="Read-only H5AD release verification and explicit State boundary",
        execution_mode="local_read_only", status="integrated",
        scientific_boundary="State outputs remain a separate cell-level evidence family and cannot be substituted for Evo2 sequence scores.",  # noqa: E501
        official_url="https://scanpy.readthedocs.io/",
    ),
    ScientificFramework(
        id="rdkit", name="RDKit", category="data",
        role="Molecular validation, canonicalization, fingerprints, and scaffold-aware splitting",
        integration="Local Tox21 molecular evidence baseline",
        execution_mode="local_deterministic", status="integrated",
        scientific_boundary="Molecular baseline results are kept separate from genomic-model results and are not interpreted as biological proof.",  # noqa: E501
        official_url="https://www.rdkit.org/docs/",
    ),
    ScientificFramework(
        id="sigma-3dmol", name="Sigma / 3Dmol.js", category="visualization",
        role="Interactive provenance graphs and returned structure inspection",
        integration="React frontend with browser-local rendering of saved artifacts",  # noqa: E501
        execution_mode="browser_local", status="integrated",
        scientific_boundary="Visualization exposes artifacts and confidence fields but does not certify model quality or biological validity.",  # noqa: E501
        official_url="https://3dmol.csb.pitt.edu/",
    ),
)


def framework_catalog() -> tuple[ScientificFramework, ...]:
    return FRAMEWORKS
