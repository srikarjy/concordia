# Scientific framework map

Concordia uses a small number of explicit framework boundaries instead of
turning every model or analysis library into a generic plugin. The registry is
available at `GET /api/frameworks` and is rendered in the frontend as the
Scientific stack view.

| Framework | Role in Concordia | Current integration | Boundary |
| --- | --- | --- | --- |
| [Evo 2](https://github.com/ArcInstitute/evo2) | DNA generation and frozen-protocol likelihood scoring | NVIDIA hosted generation; isolated ZeroGPU forward worker | Generation is not evidence. Forward output must pass checkpoint, target, hash, token-count, and numerical checks. |
| [Boltz-2](https://docs.nvidia.com/nim/bionemo/boltz2/latest/api-reference.html) | Protein, nucleic-acid, and ligand structure prediction | NVIDIA NIM, cached and attached to experiment DAGs | The current single-sequence self-reference is not a real MSA; returned structures remain computational outputs. |
| CellForge-compatible tools | Policy-checked scientific tool execution | Local process-isolated adapter and provenance events | The local adapter is not a hostile-code sandbox; fixture outputs cannot support scientific claims. |
| [AnnData / Scanpy](https://scanpy.readthedocs.io/) | Single-cell data representation and analysis context | Read-only H5AD verification for the separate State track | State is a separate cell-level evidence family, not an Evo2 substitute. |
| [RDKit](https://www.rdkit.org/docs/) | Molecular validation and baseline modeling | Tox21 molecular evidence track | Molecular baseline results are not combined with genomic results. |
| [3Dmol.js](https://3dmol.csb.pitt.edu/) and Sigma | Structure and provenance visualization | Browser-local React rendering | Visualization displays artifacts; it does not validate model quality or biology. |

## Recommended next integrations

1. Keep NVIDIA NIM as the provider boundary for hosted Evo2 and Boltz calls.
2. Add a self-hosted Boltz runner behind the same `StructurePayload` contract
   when a reproducible GPU environment is available. The open Boltz repository
   is MIT licensed and supports local CLI inference, but local weights, CUDA,
   MSA generation, and resource accounting must be pinned before scientific use.
3. Add BioNeMo/Evo2 local inference only as a second runner behind the existing
   strict `RealEvo2Scorer`; do not let a provider-specific response bypass the
   frozen study protocol.
4. Keep State/AnnData and RDKit as separate evidence families. Cross-family
   agreement can be recorded, but it must not be counted as independent proof
   unless the study declares the relationship and assay scope in advance.

These choices favor reproducibility, provenance, and graceful CPU/local
development over a broad framework marketplace. Framework status is metadata;
it does not imply that a model has been scientifically validated in this
repository.
