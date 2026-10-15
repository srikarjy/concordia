---
title: Concordia Colony Scientific Workspace
emoji: 🧬
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Concordia

**Concordia is an audit layer for AI-generated biology: it records which model, input and checkpoint produced a structure or sequence claim, tests the claim against independent evidence, and makes the whole analysis replayable.**

[Live workspace](https://srikarjy025-concordia-colony.hf.space) · [Technical overview](docs/technical-overview.md) · [Guide: usage, debugging, security](docs/guide.md) · [For biotech teams](docs/pitch.md)

![Concordia workspace: trace a claim, follow provenance, compare variants, branch designs, predict a complex, see what is real](docs/workspace.png)

## Problem

A structure model reports 0.85 confidence on an antibody–antigen complex, and the antigen is placed 20 Å from where the crystal puts it. A team that trusts that score can spend months of wet-lab work on the wrong candidate. Confidence is not evidence. Teams need to know which model, input and settings produced a result, whether independent evidence supports it, and whether someone else can replay it. Today that record lives in notebooks.

Recording lineage is a solved problem (W3C PROV, MLflow, DVC). What Concordia adds is the check: a claim gets a status from deterministic rules over independent evidence, and the rules say `UNVERIFIABLE` when the evidence is not there.

## Approach

- **Everything is an artifact.** Inputs, outputs and requests are stored by SHA-256, and a one-byte change is refused.
- **Experiments are a graph.** DNA, protein, structure and model-run nodes sit on immutable branches with a deterministic replay manifest.
- **Claims are checked by rules, not another LLM.** A claim needs independent evidence families and a passing counterfactual, or it is reported as `UNVERIFIABLE`.

```mermaid
flowchart LR
    U[Researcher or agent] --> W[Workspace and API]
    W --> L[(Append-only ledger)]
    W --> T[Registered tools]
    T --> M[Boltz-2, Evo 2, local models]
    T --> A[(Content-addressed artifacts)]
    A --> G[Evidence graph]
    L --> G
    G --> V[Rule-based verifier]
    V --> R[Claims with status and replay manifest]
```

## Results

### Preliminary benchmark, under revision

> **Read this before the table.** These predictions were run with reduced settings: 20 sampling steps, 1 recycling step, 1 sample, and single-sequence input (no MSA). The hosted NIM defaults are 50 sampling and 3 recycling steps, and the Boltz-2 paper scores antibody interfaces with DockQ over 5 samples. Nine complexes are also too few to estimate a success rate. The table says something about this configuration, not about Boltz-2. A rerun at default settings with more samples, chain-pair ipTM and an AlphaFold 3 baseline is planned, and it will replace this table.

**Boltz-2 antibody–antigen complexes released after the training cutoff (2023-06-01), scored against the experimental structure.** Selection was a seeded random draw from 94 eligible complexes, and the success rule was fixed before any result: antigen within 5 Å in the antibody frame and at least 50% of crystal contacts recovered. Failures are included.

<!-- BENCH:START -->
| PDB | Released | Model confidence | Antibody RMSD | Antigen alone | Antigen in antibody frame | Crystal contacts recovered | DockQ (CAPRI class) | Pre-registered rule |
|---|---|---|---|---|---|---|---|---|
| 8TUZ | 2024-08 | 0.81 | 1.3 Å | 13.5 Å | 18.5 Å | 70% | 0.28 (acceptable) | failure |
| 8VTD | 2025-07 | 0.90 | 1.1 Å | 0.9 Å | 14.1 Å | 3% | 0.11 (incorrect) | failure |
| 8XK6 | 2024-07 | 0.80 | 0.8 Å | 1.5 Å | 33.1 Å | 0% | 0.01 (incorrect) | failure |
| 9LY5 | 2026-03 | 0.78 | 4.2 Å | 1.3 Å | 48.5 Å | 7% | 0.03 (incorrect) | failure |
| 9NPH | 2025-08 | 0.77 | 6.7 Å | 4.0 Å | 22.5 Å | 0% | 0.05 (incorrect) | failure |
| 9NPI | 2025-08 | 0.77 | 5.0 Å | 5.6 Å | 27.1 Å | 2% | 0.04 (incorrect) | failure |
| 9OAO | 2025-06 | 0.84 | 3.2 Å | 1.1 Å | 42.4 Å | 0% | 0.01 (incorrect) | failure |
| 9SSM | 2026-02 | 0.82 | 1.1 Å | 0.9 Å | 26.2 Å | 0% | 0.08 (incorrect) | failure |
| 9VHZ | 2025-10 | 0.86 | 3.8 Å | 1.0 Å | 9.5 Å | 79% | 0.72 (medium) | failure |
| 3HFM (reference) | 1989, pre-cutoff | 0.94 | 1.4 Å | 0.8 Å | 2.1 Å | 81% | 0.81 (high) | reference |

**0 of 9 post-cutoff complexes met the pre-registered rule; 2 of 9 are acceptable or better by DockQ.**
<!-- BENCH:END -->

*What this shows.* By the pre-registered rule none of the 9 passed. By DockQ, the field's standard interface metric, 2 of 9 are correct: 9VHZ is medium quality (0.72) and 8TUZ is acceptable (0.28). The custom rule rejected both because it measures the whole antigen, so a large antigen rotated about a correct interface fails it. The rule is kept because it was fixed in advance; DockQ was added afterwards and is labeled that way in the report. Model confidence does not separate the correct predictions from the wrong ones in this set: the two correct models scored 0.81 and 0.86, while the most confident model (8VTD, 0.90) is incorrect. That gap is what an independent check is for. The reference row is a 1989 structure that is likely in the training data, so it shows the pipeline works and not that the model generalizes. Selection file, method and scripts: [`data/benchmarks/boltz2-post-cutoff-antibody-selection.json`](data/benchmarks/boltz2-post-cutoff-antibody-selection.json), [`reports/boltz2-post-cutoff-antibody-benchmark.json`](reports/boltz2-post-cutoff-antibody-benchmark.json), [`scripts/benchmark_antibody_complexes.py`](scripts/benchmark_antibody_complexes.py), [`scripts/antibody_dockq.py`](scripts/antibody_dockq.py).

**The verifier on the same nine, with the crystal held out.** Each prediction becomes a structure claim, and the verifier sees only what can be measured without the experimental structure; DockQ is used afterwards as the label. It supported none of the seven wrong poses and contradicted one (8XK6: 16 interface clashes and contacts outside the variable domain). It also could not confirm the two correct poses, returning `MISSING_EVIDENCE` for eight of nine. That is the expected result with one prediction per complex: six of the seven wrong poses are physically plausible, so a model's own output cannot verify itself. The evidence that can separate them is independent prediction (further samples, a second model, and a counterfactual run with the predicted paratope mutated), which the rerun adds. Report: [`reports/verifier-on-boltz-benchmark.json`](reports/verifier-on-boltz-benchmark.json); rules: [`src/concordia/verification/structure_rules.py`](src/concordia/verification/structure_rules.py).

**Software validation.** The Python and browser test suites run in CI (`make test`). Local throughput is about 3,300 graph operations per second, and exact ledger replay matched on 10 of 10 repetitions. The claim-verifier benchmark scores 50 of 50, but those cases are self-generated, so it checks the plumbing and not real-world accuracy. A local `qwen3:1.7b` seed passed the structured-output qualification protocol, while `phi3:latest` and `gemma3:270m` did not.

## What is implemented

- Durable run API with an append-only ledger, worker leases, idempotent creation, event streaming and replay.
- Experiment graph with branches, comparison, candidate selection and capability-token access.
- Rule-based claim verifier with five statuses and fixture rejection.
- Hosted Boltz-2 complex prediction, OpenFold2 monomer prediction and Evo 2 generation, each recorded with request and response artifacts.
- React workspace with a WebGL provenance graph, a browser-local sequence sandbox and a colony view.

### Experimental modules

These packages are research side paths. They are tested, but they are not part of the audit, verify and replay core, and nothing in the results above depends on them: `colonies/` (workflow variants selected by deterministic fitness), `scientist/` (local LLM scientist and its qualification protocol), `virtual_cell/`, `predictors/`, `explanations/` and `interventions/` (the earlier Tox21 Random Forest and TreeSHAP pipeline).

## Reproduce

```bash
make demo     # offline, no network, exits 0
make serve    # interactive workspace at http://127.0.0.1:7860
make test     # pytest, ruff, mypy, frontend build and browser tests
```

## What I would do next

1. Rerun the nine at the hosted defaults with five samples, and add AlphaFold 3 predictions and paratope-mutated reruns, so the verifier has independent evidence to work with. Then report its false-pass and false-fail rates again.
2. Grow the set to 30-50 complexes from SAbDab under the same seeded selection rule, written down before running.
3. Hash-chain the event ledger and persist it on the hosted workspace, so the audit trail survives restarts and edits are detectable.

## Related work

[Evo 2](https://github.com/ArcInstitute/evo2) · [Boltz-2](https://doi.org/10.1101/2025.06.14.659707) · [SHAP / TreeSHAP](https://github.com/shap/shap) · [CellForge](https://github.com/ArcInstitute/cellforge) · [W3C PROV](https://www.w3.org/TR/prov-overview/)

## Scientific boundaries

Nothing here is a validated biological finding or a therapeutic claim. Fixture outputs are labeled `scientific_use_allowed=false` and cannot receive scientific support status. Structure predictions are computational hypotheses. Evo 2 forward scoring, RFantibody and ProteinMPNN are not integrated yet.

## License

MIT. See [LICENSE](LICENSE) and [CITATION.cff](CITATION.cff).
