# Concordia Roadmap

This is a research plan and implementation record. The older sections below preserve the molecular study plan and its original numbering. The active Concordia Colony implementation track is recorded separately here so that planned functionality is not confused with implemented behavior. No scientist-LLM robustness or genomic research result has been produced. Null or negative findings are valid outcomes.

## Concordia Colony implementation track

- **Phase 0 — repository audit:** complete for the current Colony direction. The repository and historical molecular architecture were inspected, with the clean baseline at 16 passing tests and a clean Ruff run before backend changes.
- **Phase 1 — genomic evidence vertical slice:** complete for the explicitly labeled recorded fixture. DNA and variant validation, zero-based coordinates, fixture scoring, deterministic mutational scanning, immutable artifacts, graph construction, and fixture-rejecting backtracking are implemented.
- **Phase 2 — durable backend foundation:** complete for the local genomic fixture scope. Run contracts, the explicit state machine, an append-only SQLite/WAL ledger, optimistic concurrency, idempotent creation, content-addressed artifact metadata, deterministic replay, restart recovery, cursor event pagination, typed APIs, structured errors, durable jobs, expiring worker leases, heartbeats, stale-worker recovery, bounded infrastructure retries, cancellation, and reconnectable SSE are implemented. The API schedules work and the local worker executes it outside the request process. Fixture evidence remains barred from scientific support.
- **Phase 3 — repository and evidence-graph ingestion:** complete for the deterministic local parser scope. Markdown, Python, YAML, JSON, CSV metadata, experiment-manifest, XAI-record, and paper-metadata extraction produce typed graph nodes with exact repository-relative provenance. Invalid documents and incomplete specialized records remain as rejected candidates. Re-ingestion is content-idempotent, changed files create immutable revision lineage, and parser-version changes create new parser runs. The repository successfully ingests itself into a content-addressed graph artifact.
- **Phase 4 — CellForge and tool execution:** complete for the zero-cost local adapter. Typed execution, policy, capability, budget, and tool contracts are implemented with a versioned registry and spawned child-process execution. The seven initial scientific tools run without arbitrary shell or Python access. Denied, failed, timed-out, and successful calls are preserved as immutable artifacts, ledger events, and provenance graphs. Network, traversal, symlink, timeout, output-size, and artifact-integrity failures are covered by tests. The adapter is intended for trusted registered handlers; an external CellForge runtime remains a replaceable future adapter rather than a local requirement.
- **Phase 5 — seed scientist runtime:** complete for the local software fixture. Four strict turn contracts, a loopback Ollama adapter, versioned genomic prompts, bounded tool execution, raw-response preservation, reference checks, replay, and deterministic qualification metrics are implemented. Failed `phi3:latest` and `gemma3:270m` attempts remain preserved. With prompt `genomic-scientist-v3`, `qwen3:1.7b` passed all declared thresholds in two repetitions and is pinned by checkpoint digest. This qualifies protocol behavior only, not biological judgment. See [the qualification guide](seed-scientist.md).
- **Phase 6 — colony evolution:** complete for the deterministic software fixture. Immutable digital genomes, eight bounded mutation operators, complete ancestry, generation barriers, isolated worker inputs, sequential-by-default bounded concurrency, cancellation, event-ledger resume, budget and stagnation stops, full fitness vectors, deterministic weighted selection, and inspectable extinction are implemented. A seed produces three descendants across two generations with reproducible selection. Fixture outputs cannot support scientific claims. See [the colony guide](colonies.md).
- **Phase 7 — independent verification:** implemented for typed evidence observations and content-addressed provenance. Five family contracts, independence matching, counterfactual requirements, scope checks, complete dependency integrity, fixture rejection, contradictions, missingness, and repeat/window summaries are tested. The first measurement pair is mutagenesis and regulatory annotation overlap. Real study collection remains Phase 9. See [verification](verification.md).
- **Phase 8 — interactive workspace:** complete for the saved fixture demonstration. The React/TypeScript/Vite mission-control workspace separates investigation, bounded sequence replay, colony evolution, and provenance into focused views. It includes guided claim-to-evidence tracing, a browser-local replay of 144 persisted fixture substitutions, generation scrubbing, component-level member inspection, event controls, an interactive WebGL graph with keyboard fallback, responsive layouts, and reduced-motion styling. The replay makes no mutation request, invokes no model, and renders only persisted artifacts that remain ineligible for scientific use.
- **Phase 9 — real scientific validation:** inputs are frozen for a two-variant HBB promoter pilot, but outcome collection is not complete. Protocol v1 is preserved, while a pre-execution v2 corrects its non-immutable adapter label and missing causal-scoring details. V2 pins Evo2 source 0.6.0, the released 7B checkpoint revision and digest, 8,191 next-token terms per 8,192-base window, and alternate-minus-reference scoring before outcomes. A checksum-validated K562 DNase source and both in-window peaks are preserved, including no direct overlap at either variant base. No real Evo2, SAE, or comparator result is available, so no support status or scientific finding is claimed.
- **Phase 10 — hardening and portfolio release:** complete for the local software release. CI, reproducibility checks, deployment instructions, a non-root CPU Docker image, and the public free Hugging Face Space are available. CI action code is commit-pinned with read-only repository permissions. The public workspace publishes a curated six-operation, GET-only OpenAPI contract for saved evidence inspection; it does not expose run mutation, arbitrary sequences, CellForge execution, or model inference. Real scientific validation remains a separate gated study and is not represented by the fixture deployment.
- **Post-Phase 10 readiness:** a strict real-Evo2 boundary, a measured non-scientific NVIDIA hosted-generation smoke test, SAE and cross-model validity contracts, measured local-Qwen colony execution, bounded CELLxGENE ingestion, a pinned official State source verifier, an Arc State-compatible virtual-cell sandbox, and an immutable K562 State release verifier are implemented. The selected release pins a matched 188,590-cell by 2,000-gene H5AD and checkpoint under user-accepted non-commercial terms without loading model serialization. A ZeroGPU probe found a BF16-capable 48 GiB MIG allocation. A subsequent Python 3.12 runtime qualification verified pinned Evo2, Vortex, FlashAttention, installed source bytes, and the complete 7B checkpoint without deserializing it. Real Evo2/SAE/comparator/State output collection, model-load and numerical qualification, collaboration, and measured scale-out remain gated extensions.

## Phase 0 — Repository Foundation

Current deliverables: project README, this roadmap, MIT license, and practical Git exclusions. The README establishes architecture, experimental scope, reproducibility expectations, and component boundaries.

The expanded foundation will add dedicated architecture, experiment-design, and reproducibility documents; minimal package metadata and editor configuration; and documented directories for configuration, external data, processed data, frozen evidence, experiment manifests, reports, and tests. Future source boundaries are `predictors`, `explanations`, `evidence`, `scientist`, `interventions`, `evaluation`, and `reporting`. Empty directories need only placeholders; no implementation files are needed for scaffolding.

**Completion criteria:** the initial documentation clearly distinguishes plans from results, specifies one scientist LLM plus a deterministic evaluator, and contains no unnecessary service architecture. Complete.

## Phase 1 — Baseline Toxicity Predictor

- Obtain and version Tox21; record source, usage terms, checksums, and assay label definitions. Isolate NR-AhR and explicitly handle missing labels without treating them as negatives.
- Validate molecules with RDKit. Define canonical SMILES, duplicate handling, invalid-input handling, and conflicting-label policy.
- Create fixed training, validation, and test partitions. Prefer a documented scaffold-aware strategy; keep duplicate structures together and audit leakage.
- Compute Morgan fingerprints with recorded radius, size, chirality settings, and software versions.
- Train a Random Forest with recorded seeds and class-imbalance handling. Use validation data for hyperparameters, thresholds, and any calibration decisions.
- Evaluate discrimination and class-sensitive performance, including ROC-AUC and precision-recall measures with uncertainty where appropriate. Record probability limitations.
- Persist the model, split manifest, preprocessing configuration, environment, and performance artifacts.

**Completion criteria:** a reproducible baseline artifact predicts held-out valid molecules; split and label audits pass; performance and limitations are reported without selecting the test cohort based on favorable outcomes. Met for the baseline artifact. Freeze the approximately 30-molecule study cohort separately from training before the MVP.

## Phase 2 — XAI Evidence Generation

- Use TreeSHAP for the fixed baseline; verify the supported model/output configuration.
- Specify explained class, output scale, expected value, feature ordering, background/reference data where applicable, and attribution settings.
- Record fingerprint-feature attributions and connect features to molecular context only where the mapping is defensible. Document hashed-bit collisions and multiple matching environments; do not imply unique atom-level or causal interpretation.
- Validate finite values, feature consistency, and reconstruction/additivity within a documented tolerance appropriate to the chosen configuration.
- Serialize stable explanation artifacts and frozen packets containing molecule, prediction, metadata, attributions, and a fixed selection of curated documents.
- Start with approximately eight real supporting documents. Record source, version, excerpt boundaries, usage rights, and evidence identifiers. Define exact packet schemas in this phase, not in the initial repository setup.

**Completion criteria:** every cohort molecule has a traceable model explanation and content-hashed packet; packets can be replayed without retraining, regenerating explanations, or retrieving new documents. Development runs now emit validated TreeSHAP artifacts and packet manifests. The cohort-level completion gate remains open until the study cohort and permitted evidence documents are frozen.

## Phase 3 — Scientist LLM Interface

- Map packets to a versioned prompt using a direct provider API.
- Define a claim taxonomy distinguishing prediction restatements, attribution-based interpretations, and biological/mechanistic hypotheses.
- Define claim text, type, confidence, evidence references, evidence strength, and prediction relationship in a structured contract; validate it with Pydantic.
- Specify confidence scales, stable evidence identifiers, and a claim-comparison strategy before the main experiment.
- Preserve exact requests, raw responses, parsed claims, validation failures, provider metadata, and any retries. Predefine retry limits and failure handling to avoid selective inclusion.
- Record model identifiers and generation parameters, including temperature; assess repeated calls under the same settings. Each condition starts without previous responses in context.

**Completion criteria:** the interface can preserve and validate outputs for frozen packets, record failures, and replay saved responses. The local Ollama adapter, versioned prompt, Pydantic response contract, and content-hashed run records are implemented. A model qualification run and the cohort matrix remain before Phase 3 is complete. No agent framework, debate, or evaluator-driven correction loop is introduced.

The optional tool-enabled extension begins here. A local deny-by-default gateway exists for a separate researcher-mode ablation. The evaluation policy exposes zero tools and permits zero tool calls; the packet-only MVP remains the primary comparison. Any tool-enabled run must have a distinct condition identifier and cannot be merged with packet-only results.

Run `OLLAMA_NO_CLOUD=1 concordia doctor` before qualification. The diagnostic is local-only and does not pull model weights automatically.

## Phase 4 — Intervention Engine

- Implement an identity control, explanation withholding, and explanation shuffling first.
- For shuffling, precompute a seeded donor mapping with no self-donors. Keep the assay, predictor, explanation format, and declared donor-selection constraints consistent.
- Change only the designated explanation payload. Preserve recipient molecule, prediction, prompt, documents, and other unrelated context. Keep actual donor provenance in the audit record without revealing experimental labels to the scientist.
- Remove all designated explanation content when withholding, including any duplicate attribution-derived summaries. Use a predeclared representation for absent evidence.
- After the initial conditions work, define deterministic corruption such as sign inversion of a recorded subset of attribution values. Record magnitude, selection rule, affected fields, and seed; keep this extension outside the minimum three-condition experiment.
- Give each transformation an identifier/version and an auditable manifest linking parent and resulting packet hashes.

**Completion criteria:** identical inputs and configuration produce identical variants; audits demonstrate that unrelated fields remain unchanged. Shuffling has no self-donors and no accidental provenance disclosure. Corruption has separately documented validation before use.

## Phase 5 — Deterministic Evaluation

- Predefine claim matching: use structured categories and explicit rules where possible; use fixed human mappings for semantic equivalence that cannot be established mechanically.
- Define retention, additions, and removals relative to control, including denominators and empty-claim cases.
- Compare confidence for matched claims; separately account for removed or added claims rather than inventing missing confidence values.
- Record evidence-reference changes, reference validity, unsupported-claim rates, contradiction rates, and intervention sensitivity. Distinguish prediction-grounded claims from explanation-dependent claims.
- Define human scoring rubrics for scientific support and semantic contradictions. Have independent reviewers score a subset where feasible, record disagreements, and preserve adjudications.
- Report schema failures, unavailable outputs, and unmatched claims explicitly. Do not silently filter problematic runs.
- The evaluator consumes validated claims and any fixed annotations and produces metrics/comparison results only. It never generates alternative conclusions, rewrites responses, or coaches the scientist.

**Completion criteria:** saved inputs and annotation versions yield identical metrics; definitions, denominators, matching rules, and limitations are documented. Manual scientific judgment is clearly distinguished from automated reference checks.

## Phase 6 — MVP Experiment

- Freeze approximately 30 held-out molecules from NR-AhR, one predictor, one XAI method, one scientist model, approximately eight documents, and the control/withheld/shuffled conditions.
- Record inclusion/exclusion criteria before reviewing LLM outcomes. Describe class balance and prediction-confidence coverage; this is a small exploratory study.
- Predeclare hypotheses: explanation-dependent claims may become more qualified when explanations are withheld; shuffled evidence may alter explanations or expose inappropriate confidence. Stable prediction restatements may be warranted. None of these outcomes is assumed.
- Specify repeat counts and generation settings before collection. Randomize or balance condition order, use independent contexts, and pair comparisons by molecule. Repeated calls are not independent additional molecules.
- Store molecule input, model prediction, original explanation, transformed packet, intervention manifest, raw response, structured claims, validation status, metrics, and immutable experiment manifest.
- Audit confounders: missing-evidence wording, prompt length, donor compatibility, documentary support, prior molecular knowledge, fingerprint ambiguity, predictor quality, provider drift, and sampling variability.

**Completion criteria:** the frozen matrix of molecules, conditions, and repetitions is accounted for, including failures; all results can be traced to immutable input artifacts. No test-set tuning or selective rerunning based on favorable scientific conclusions.

## Phase 7 — Analysis and Findings

- Aggregate paired intervention differences, claim changes, confidence distributions, and evidence dependence.
- Estimate uncertainty with the molecule as the sampling unit; distinguish within-molecule generation variance from between-molecule variation. Avoid overstating significance in a small exploratory cohort.
- Present molecule-level case studies selected with transparent criteria, including faithful responses and ambiguous cases as well as failures if observed.
- Analyze manual scoring and disagreements; report limitations of reference validity, semantic matching, XAI interpretation, and assay-specific generalization.
- Publish a reproducible findings report with protocol deviations, missingness, model performance context, and null/negative results where observed.

**Completion criteria:** every table and claim is traceable to saved outputs and documented analysis; the report answers the research question to the extent supported without predetermining the outcome.

## Phase 8 — Stronger Molecular Predictor

Only after the baseline framework works, evaluate Chemprop v2 with PyTorch and an appropriate Integrated Gradients / Captum integration. Verify model compatibility, attribution targets, baselines, and numerical checks before drawing comparisons.

Repeat selected experiments while preserving molecule selection and LLM/evaluation settings where possible. Document changes in predictive performance, attribution granularity, and evidence format as potential confounders. Compare whether observations generalize across predictor/XAI combinations rather than assuming an improvement.

**Completion criteria:** the graph-model pathway produces traceable validated evidence, and the comparative report separates robustness observations from predictor and explanation-method differences.

## Phase 9 — Portfolio / Research Presentation

Produce reproducible figures and experiment tables, an architecture diagram, a methodology explanation, limitations, and a minimal static HTML findings report. Link shareable manifests and artifacts with versioned access instructions. Add concise reproduction instructions once actual commands exist.

**Completion criteria:** readers can understand the scientific question, inspect evidence behind conclusions, and reproduce the reported analysis from saved artifacts. No React application or dashboard is required.

## Phase 10 — Optional Genomic Generalization with Evo 2

This is a separate follow-up study, not part of the Tox21 MVP and not a replacement for Chemprop. Evo 2 models nucleotide sequences rather than small molecules, so this phase changes the scientific domain while testing whether Concordia's evidence-intervention framework generalizes.

A zero-cost software vertical slice now validates DNA and variant contracts, records deterministic fixture scores, performs position-level mutational scans, stores content-addressed artifacts, constructs a provenance path, and refuses to treat fixture-backed claims as scientific evidence. Actual Evo 2 inference and biological validation remain future work requiring compatible compute and a declared genomic task.

- Select a validated genomic prediction or variant-scoring task with real labeled data. Sequence generation alone is not a suitable predictor/XAI experiment.
- Freeze the exact Evo 2 checkpoint/runtime, DNA input, task-specific output, and local forward-pass artifacts. Hosted Evo 2 generation does not expose the layer-output interface needed for this plan.
- Select an established attribution or deterministic perturbation method appropriate to the validated genomic task; do not present raw embeddings as explanations and do not invent a new XAI method.
- Build a genomic evidence-packet schema without changing the core guarantees: one scientist LLM, independent conditions, frozen evidence, controlled withheld/shuffled interventions, and deterministic comparison.
- Validate biological scope, sequence orientation, windowing, reference assembly, variant representation, output calibration, attribution target, and leakage controls before collecting LLM responses.
- Treat Evo 2 outputs as model evidence rather than biological truth. Independently validate any biological interpretation used in the study.

The official Evo 2 repository documents a 7B bfloat16 path without Transformer Engine on supported Linux/CUDA hardware; larger or FP8 deployments have stricter requirements. A measured ZeroGPU allocation provides a BF16-capable 48 GiB MIG candidate. The pinned Python 3.12/Evo2/Vortex/FlashAttention runtime now imports successfully and the full checkpoint hash matches, but the model has not been loaded or executed and numerical compatibility remains unverified. Use hosted generation only for API exploration, not as a substitute for forward outputs.

**Entry criteria:** Phases 0–7 are complete, the molecular study has stable packet/intervention/evaluation interfaces, a concrete genomic task and dataset have been chosen, and suitable local compute is available. **Completion criteria:** the genomic predictor and explanation have their own empirical validation, every packet is replayable, and cross-domain conclusions distinguish Evo 2/task effects from Concordia framework effects.

## Artifact and Reproducibility Contract

Future configuration files will select assay, dataset version, seeds, model/XAI settings, prompt, generation parameters, intervention mapping, and repetitions without containing secrets. Future data documentation will distinguish external raw inputs, processed derivatives, and frozen evidence; provenance and redistribution rights must be recorded.

Experiment manifests will link dataset checksums, molecule identifiers, split versions, predictor hashes, explanation versions, packet hashes, prompt versions, exact model identifiers, generation settings, intervention identifiers, raw-response locations, environment locks, code revisions, annotations, and metric definitions. A changed input produces a new run identity; derived results never overwrite raw evidence.

Keep small, reviewable configurations, provenance records, prompts, manifests, and permitted findings in Git. Store bulky datasets, model binaries, raw experiment payloads, and restricted documents outside Git with checksums and retrieval instructions. Optional tracking may use one of MLflow or Weights & Biases; neither is needed for this foundation.

Frozen evidence isolates the experimental manipulation from changes in retrieval, model training, or explanation generation. Replaying saved responses supports deterministic analysis; repeating hosted generation may produce different responses and must be treated as a new observation.
