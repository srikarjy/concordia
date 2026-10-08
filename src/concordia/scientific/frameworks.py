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
        id="rfantibody", name="RFantibody / RFdiffusion", category="structure_model",
        role="Planned antibody and nanobody backbone generation",
        integration="External GPU worker contract is planned; no local model execution is enabled",
        execution_mode="planned_external_gpu_worker", status="planned",
        scientific_boundary="Generated backbones require sequence design, complex refolding, interface checks, and experimental validation before any scientific conclusion.",  # noqa: E501
        official_url="https://github.com/RosettaCommons/RFantibody",
    ),
    ScientificFramework(
        id="proteinmpnn", name="ProteinMPNN", category="structure_model",
        role="Planned antibody sequence design from generated backbones",
        integration=(
            "External GPU worker contract is planned; checkpoint and sampling provenance "
            "will be required"
        ),
        execution_mode="planned_external_gpu_worker", status="planned",
        scientific_boundary="Designed sequences are computational candidates and do not establish folding, binding, expression, or developability.",  # noqa: E501
        official_url="https://github.com/dauparas/ProteinMPNN",
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
    ScientificFramework(
        id="react-flow", name="React Flow", category="visualization",
        role="Planned editable workflow and experiment-DAG canvas",
        integration=(
            "Candidate for typed node editing, handles, validation, and save/restore "
            "interactions"
        ),
        execution_mode="planned_browser_local", status="planned",
        scientific_boundary=(
            "An editable graph changes workflow state only; it cannot turn computational "
            "artifacts into scientific evidence."
        ),
        official_url="https://reactflow.dev/",
    ),
    ScientificFramework(
        id="molstar-ngl", name="Mol* / NGL Viewer", category="visualization",
        role="Planned higher-fidelity biomolecular structure and annotation inspection",
        integration=(
            "Candidate structure viewer for chain annotations, selections, and large "
            "complex inspection"
        ),
        execution_mode="planned_browser_local", status="planned",
        scientific_boundary=(
            "A richer molecular renderer improves inspection and annotation, not structure "
            "accuracy or biological validation."
        ),
        official_url="https://github.com/molstar/molstar",
    ),
    ScientificFramework(
        id="observable-plot", name="Observable Plot", category="visualization",
        role="Planned benchmark and evidence-metric charts",
        integration="Candidate for compact latency, replay, and claim-verifier metric views",
        execution_mode="planned_browser_local", status="planned",
        scientific_boundary=(
            "Plots summarize declared measurements; they do not establish model quality "
            "or biological truth."
        ),
        official_url="https://observablehq.github.io/plot/",
    ),
)


def framework_catalog() -> tuple[ScientificFramework, ...]:
    return FRAMEWORKS
