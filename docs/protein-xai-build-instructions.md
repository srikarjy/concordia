# Concordia protein XAI: research and product build instructions

> **Portfolio delivery scope (2026-10-20):**
> [PORTFOLIO_FINISH_PLAN.md](PORTFOLIO_FINISH_PLAN.md) controls the next release.
> Use this document for technical rationale and scientific safeguards.
> Its broader research and hosted-service ambitions are not all prerequisites
> for the bounded portfolio milestone.

Date: 2026-10-19. Status: proposed implementation plan, grounded in the local
checkout and live GitHub audit. This document does not claim that the planned
features are implemented or scientifically validated.

Read the [repository audit](audits/2026-10-19-repository-audit.md) and
[file inventory](audits/2026-10-19-file-inventory.tsv) before implementation.
The audit records local HEAD `0cc262a`, the dirty working tree, and the different
GitHub branch heads. Recheck those identities when starting work.

For copy-paste assignments and model roles, use
[the model handoff pack](protein-xai-agent-tasks.md).

## 1. Product decision

Build a protein mutation evidence workbench with an experimentally evaluated XAI
layer. Its first researcher is a computational protein engineer reviewing which
single substitutions deserve an experiment and explaining the decision to a
collaborator. The first property is folding stability within a declared assay
and model scope.

The researcher should be able to:

1. Load a reference sequence, a mapped structure when needed, candidate mutations,
   and existing prediction or assay tables.
2. See which predictions are applicable, which disagree, and which should be
   refused or treated as uncertain.
3. Inspect an explanation of one precisely identified model output, alongside
   its fidelity tests and limitations.
4. Select, exclude, or defer candidates with a recorded reason.
5. Import subsequent measurements without rewriting the earlier decision.
6. Export a self-contained report that another researcher can verify and replay.

The product hypothesis is that this makes mutation review more reproducible and
helps researchers detect unsupported model reasoning. Improved experimental hit
rate is a separate hypothesis requiring prospective evidence.

**Scope assumption:** prioritize single-mutation stability. If structure-claim
assessment becomes the first product priority, use section 11 and retain the
same evidence/review foundation. Record that scope decision before starting the
corresponding scientific evaluation.

## 2. Preserve and reuse what already works

| Existing component | Instruction |
| --- | --- |
| `src/concordia/review/workflow.py` and `api/reviews.py` | Extend the validated review, revision, decision, assay-import, and export flow. Do not create another competing review database. |
| `frontend/src/review-main.tsx` | Make this the main researcher workflow. Keep the frozen 1IGV example as a clearly labeled example. |
| `campaigns/assay.py`, `schema.py`, `study.py`, `validation.py` | Reuse assay semantics and study identities; adapt contracts explicitly where the protein-XAI workflow needs additional fields. |
| `storage/content.py`, `events/sqlite.py`, `experiments/`, `campaigns/replay.py` | Reuse artifact identities, execution lineage, and replay concepts. Verify actual bytes when replaying; references alone do not establish availability or integrity. |
| `stability/contracts.py`, `request.py`, `measured.py`, `ranker.py` | Preserve the current 1IGV regression path and sign/refusal contracts while adding a separate, scoped predictor adapter. |
| `frontend/src/molstar-viewer.tsx` | Extend residue selection and evidence overlays after mapping tests pass. Preserve keyboard-accessible tables. |
| `verification/cross.py`, `structure_rules.py` | Keep the structure rule pack, including `StructureScope`. Repair provenance and interpretation boundaries before expanding claims. |
| Existing molecular, genomic, colony, and virtual-cell workflows | Preserve working APIs/tests. Keep them outside the first protein product journey unless they serve a defined task. |

Do not restart the application, replace the framework, add an agent platform, or
train a foundation model to deliver this first workflow. The existing review
and evidence infrastructure is the foundation.

## 3. First fix reproducibility and release coherence

Complete this phase before adding scientific claims or a public XAI endpoint.

### Repository and CI

- Preserve all existing modified/untracked files. Record a baseline diff and
  assign changes to their owners before selectively committing anything.
- Reconcile local `feature/antibody-boltz-concordia` with both remote branches in
  an isolated checkout/worktree. Main and the remote feature branch have diverged;
  do not reset, force-push, or assume either branch contains all current features.
- Repair the real CI dependency failures. Current GitHub Python collection
  imports `torch` through uncertainty-evaluation scripts; the CI environment
  does not install it. Move heavy imports into the functions that need them
  when lightweight tests do not require inference. Add a separately declared
  model test environment for tests that actually require Torch/Transformers.
- The published frontend job failed because `Bio` was missing. Local dependency
  changes address part of this gap; prove the selected solution in a fresh
  environment and on the reviewed GitHub revision.
- Make dependency manifests and lock files agree. Test the install profile used
  by each deployment, rather than relying on packages already in this `.venv`.
- Replace ambiguous whole-tree mypy discovery with explicit package roots and
  independent deployment-script checks. Multiple unrelated `app.py` entrypoints
  currently collide. Required checks must not hide failures behind
  `continue-on-error`.
- Add the local-review and public-page browser suites to the appropriate CI jobs.
  They are not included in the existing default workspace browser command.
- Inspect the built wheel/container in a clean environment. Ensure bundled data
  and source-relative paths work without the developer checkout. An offline
  demonstration may require a separate asset-fetch/install step first.

### Assets and model identity

- Produce a versioned artifact manifest covering the table, structures, embeddings,
  ensemble, ranker, calibration, model source revision, and weight-file digests.
  Some required measured-stability assets are currently ignored local files.
  Provide a documented, licensed download or reproducible preparation path.
- Enforce checkpoint revisions in actual loader calls. The current predictor
  records `CHECKPOINT_COMMIT`, but its `from_pretrained` calls do not pass
  `revision=...`. Check the baseline script and runtime loader too. Record the
  resolved revision and weight digests, not just an intended registry value.
- Validate trusted artifact digests **before** deserializing joblib/pickle model
  files. Never accept arbitrary uploaded serialized Python objects.
- Move T2 recalibration out of `MeasuredStabilityEngine.__init__` into a versioned
  preparation step. Serving must load immutable calibration and must not rewrite
  shared data or silently refit preprocessing during requests/startup.
- Pass an explicit asset root instead of relying on the process working directory.
- Preserve old benchmark manifests and outputs. Corrections produce new versions
  with a reason and parent identity.

### Routes and deployment ownership

- Define explicit routes for review, the 1IGV example, and historical demos.
  The current production build includes only `stability.html`; its “Variant
  review workspace” link to `/` is rewritten back to that page. Copying replay
  JSON/HTML assets does not ship the React review entrypoint.
- Build and test every intended entrypoint under the production rewrites and
  security headers. Keep local writable reviews local until authenticated,
  tenant-scoped persistence is implemented and tested.
- Document which gateway owns each operation: local API, HF owner gateway, or
  Supabase user gateway. Resolve conflicting deployment/credential instructions
  before changing any hosted configuration.
- Separate historical connector smoke-test records from current availability.
  A hard-coded registry status is not a live health check.

**Exit evidence:** fresh-install checks; required CI green on the reviewed commit;
working review/example navigation; versioned assets with checked digests; no
changes to scientific outputs without a new artifact version.

## 4. Define the prediction before defining the explanation

Introduce typed contracts, provisionally in `src/concordia/protein_xai/`, with a
small adapter boundary. These are proposed modules, not existing APIs.

| Record | Required content |
| --- | --- |
| `ProteinInput` | Normalized sequence and digest; structure bytes/digest and origin; chain; sequence-to-structure mapping; missing residues; insertion codes; selected conformer; numbering convention. |
| `PredictionTarget` | Property, assay scope, model output name, units, sign convention, mutation, reference context, supported scope, and output transform. |
| `ModelExecution` | Input/target identities; source commit; resolved checkpoint/weights; settings; seeds; software/device versions; terminal status; raw output artifact; timing and measured memory; limitations. |
| `ExplanationSpec` | Exact execution/output to explain; method/version; baseline or intervention distribution; feature space; aggregation; sample/step budget; random seed; tolerances. |
| `ExplanationResult` | Spec and execution references; residue/feature values; raw explanation artifact; numerical diagnostics; unsupported features; execution status. |
| `ExplanationValidation` | Protocol and split identities; fidelity/sanity/stability results; controls; uncertainty; failures; evidence eligibility derived by the gate. |
| Review evidence link | Immutable references from the existing review revision to prediction, explanation, validation, and assay records. |

Do not add a second event ledger. Store large numerical arrays in the existing
content-addressed store; store references and typed summaries in the workflow.

For stability, specify the thermodynamic convention in words and symbols. Current
normalized labels use mutant minus reference folding stability, with positive
values meaning more stable. A model using positive values for destabilization
needs an explicit tested conversion. “ΔΔG” without a convention is insufficient.

The current rank average combines ThermoMPNN and one-hot scores, while displayed
numeric predictions/intervals come from a ridge ensemble over ESM site embeddings.
They are distinct prediction targets. Label them separately in every UI/export.

For rank explanations, retain the full candidate cohort, raw component values,
component ranks, tie policy, penalties, and aggregation formula. Current ranks
are relative to the submitted list. Decide whether that behavior is intended or
whether a fixed candidate universe is required; version any change. Test cohort
changes, tied scores, permutations, and repeated candidate IDs.

## 5. Build one executable protein model adapter

Start by assessing the pinned open-weight ThermoMPNN path already used by the
repository. Its official implementation predicts stability changes for point
mutants and provides custom-PDB inference. This makes it a plausible first
adapter, subject to input, checkpoint, compute, and leakage checks; it is not a
claim that Concordia has already generalized it. [ThermoMPNN source](https://github.com/Kuhlman-Lab/ThermoMPNN)

1. Reproduce a small upstream example with the pinned weights and explicit sign
   convention. Save raw outputs and compare them with the adapter within a
   declared numerical tolerance.
2. Measure CPU runtime and memory on a small protein before choosing limits.
   Start with cached/local resources and a $0 paid-compute budget. Do not infer
   production capacity from one warm request.
3. Confirm the adapter computes fresh predictions for valid new inputs. The
   current HF scoring wrapper serves the frozen measured workflow; its endpoint
   name and bundled weights do not prove new ThermoMPNN inference per request.
4. Validate wild-type identity, sequence/structure alignment, chain selection,
   missing residues, nonstandard residues, and candidate uniqueness before
   inference. Refuse unsupported contexts with a specific reason.
5. Keep single substitutions as the initial model scope. The review workflow may
   store multi-mutants without the predictor being allowed to score them.
6. Treat new-protein predictions as uncalibrated until a relevant held-out
   evaluation supports uncertainty. Do not attach the 1IGV interval to them.
7. Add a cheap explicit baseline and retain the existing frozen ranker as a
   separate reference. An explanation layer does not establish predictive value.

**Exit evidence:** upstream parity, correct mapping/signs, immutable run record,
measured resource cost, meaningful failure tests, and exact saved-output replay.

## 6. Implement XAI in a scientifically defensible order

### A. Explain the decision policy

Expose how source scores, constraints, missing evidence, refusals, and human
overrides affected the review. This is already close to the existing workflow
and is useful immediately. Call it a decision trace; it does not explain the
internal computation of a protein model.

### B. Add a controlled model-sensitivity baseline

Define a scalar model output `f(sequence, structure, mutation)` and declare what
is held fixed. A substitution landscape compares the model's predictions across
candidate substitutions; it is useful context, but is not automatically an
attribution map for one prediction.

For an adapter that supports changing reference sequence context, one possible
residue-sensitivity experiment is:

```text
I(j, b) = f(sequence with context residue j changed to b, fixed structure, mutation)
          - f(original sequence, fixed structure, mutation)
```

Use `j` different from the focal mutation site. Predeclare allowed substitutions,
positions, sampling, and aggregation. Check adapter support before implementing
this experiment. Keeping coordinates fixed is a model intervention with an
explicit approximation; it does not simulate relaxation or measure biological
epistasis. Unsupported or implausible contexts must be reported, not hidden.

Use matched controls for distance, exposure, and number/type of changes. Record
all queried outputs. A full all-residue/all-amino-acid sweep is unnecessary for
the first feasibility test and may be expensive.

### C. Add one attribution method only after feasibility checks

If the adapter exposes a differentiable output, evaluate integrated gradients
or another explicitly specified method against the sensitivity baseline. Name
the tensor being attributed, scalar target, reference input, integration path,
and residue aggregation. An embedding coordinate is not a residue until the
mapping/aggregation is defined. Interpolated embeddings can leave the distribution
of valid proteins; include this limitation and baseline-sensitivity analysis.

Integrated gradients provides a defined attribution construction and completeness
property for a chosen input/baseline pair; it does not supply biological causal
proof. [Original method](https://arxiv.org/abs/1703.01365)

Require:

- Numerical convergence and completeness checks where the method claims them.
- Changes under appropriate model-parameter randomization; constant-model and
  linear-model controls with known behavior.
- Label-randomization checks for models/baselines that can actually be retrained;
  record “not evaluated” for unavailable training rather than fabricating a check.
- Fidelity evaluated on held-out interventions, with matched random/structural
  controls. Do not validate an occlusion explanation solely by repeating the
  identical occlusions used to construct it.
- Sensitivity to baseline choice, small allowed input perturbations, and stochastic
  execution. Separate numerical instability from meaningful model sensitivity.
- Failure visibility. An attractive heatmap can fail these tests.

The randomization requirements are motivated by the original saliency sanity-check
study; applicability must be assessed for the selected protein architecture.
[Sanity Checks for Saliency Maps](https://arxiv.org/abs/1810.03292)

Attention, contact proximity, pLDDT, and an LLM-generated rationale must not be
renamed model attribution. They can be displayed as separate contextual tracks.

**Exit evidence:** one replayable explanation for one exact prediction, with a
declared baseline, mapping, control comparison, and a visible validation status.

## 7. Evaluate three different questions separately

| Question | Required comparison | What it cannot establish alone |
| --- | --- | --- |
| Is the prediction useful? | Experimental labels against constant/simple sequence or structure baselines, on a frozen split. | Explanation fidelity or mechanism. |
| Does the explanation reflect this model? | Numerical/sanity checks and held-out intervention response against random and structural baselines. | Correctness of the model's biological prediction. |
| Does the tool help researchers? | Existing review process versus Concordia on comparable tasks; reproducibility, error detection, completion time, and user feedback. | Better experimental hit rate without prospective assays. |

### Dataset and leakage protocol

- Use 1IGV as a regression/example case, not evidence for generalization to new
  proteins. Start a small multi-protein feasibility pilot, then freeze a separate
  evaluation before inspecting its outcomes.
- Inventory training/fine-tuning data and model selection for every predictor,
  including upstream pretrained models where disclosed. ThermoMPNN's released
  default model uses Megascale training data; Tsuboyama data cannot be assumed
  independent merely because Concordia has not trained on it.
- Record exact and sequence-family overlap, structure identity, assay duplicates,
  and data release versions. An identifier search for `1IGV` is not a homology
  leakage audit. Unknown upstream exposure remains “unknown.”
- Separate training, validation, calibration, and final test identities. Split by
  protein/family for new-protein claims. Position holdout within one protein
  answers a narrower question. Do not use final labels to choose methods,
  thresholds, candidate sets, or explanation baselines.
- Preserve experimental conditions, units, error estimates, censoring, assay
  failures, and replicates. Tsuboyama proteolysis-derived estimates have assay
  assumptions; they are not every possible stability/function phenotype.
  [Dataset paper](https://www.nature.com/articles/s41586-023-06328-6)
- ProteinGym is a useful evaluation reference, but its assays measure varied
  properties. Select compatible tasks and retain assay identities; do not pool
  all fitness values as interchangeable ΔΔG labels.
  [ProteinGym source](https://github.com/OATML-Markslab/ProteinGym)
- Freeze a protocol before scaling: primary endpoint, unit of analysis, comparator,
  number of proteins/families, inclusion/exclusion rules, seeds, resource limit,
  and stopping rule. Justify sample size using the intended claim and pilot
  variance; a fixed small number does not guarantee adequate evidence.

### Analysis and reporting

- Report per-protein predictive correlation/ranking and errors only where units
  permit. Include top-k enrichment or precision when selection is the actual job.
  Fix k and the candidate universe before viewing final outcomes.
- Report interval coverage **and width**, refusal rate, and performance on
  accepted versus rejected inputs. The current 94.1% coverage/4.67 kcal/mol width
  is a recorded 1IGV holdout result, not an individual success probability.
- Report fidelity and explanation stability independently of predictive metrics.
  Agreement with annotations is auxiliary evidence, not mechanistic ground truth.
- Aggregate across proteins/families without letting the largest assay dominate.
  Use paired comparisons and uncertainty at the independent protein/family level.
  Variant rows and repeated seeds are not independent biological replicates.
- Do not label fold standard deviations as significance tests. Report effect
  sizes, uncertainty, negative results, exclusions, and all evaluated baselines.
- Compare selective prediction with an always-abstain policy and useful coverage
  targets. Zero false passes with zero accepted cases is not demonstrated utility.
- Avoid universal conformal-coverage claims under a changed protein/position
  distribution. State the calibration population and check empirical transfer.

**Scientific release gate:** the frozen primary comparison meets its predeclared
criterion, uncertainty is reported, and failures remain accessible. Otherwise
ship a clearly labeled research/diagnostic workflow without a performance claim.

## 8. Connect XAI to the existing review experience

Use one visible journey: **input → prediction → explanation → evidence → decision
→ assay outcome → export**. The central screen is the candidate review, not a
catalog of model connectors.

For each candidate show:

- Mutation and exact numbering/chain; property, units, and direction.
- Predictor name/version and whether the value was imported, replayed, or newly
  executed; uncertainty only within its validated scope.
- Explanation target/method/baseline and validation status, with a residue table
  synchronized to the structure. Missing residues must stay visibly unmapped.
- Independent evidence, contradictions, missing evidence, and refusal reasons.
- Researcher decision/reason; protected-position override when allowed by the
  review policy. Human override must not silently enable a refused model call.

Keep optional prose deterministic where possible. If an LLM summarizes the
record, bind factual statements to evidence IDs and prohibit invented values,
causal language, or unsupported eligibility upgrades. The current extraction
schema can assist input parsing; it is not the protein explanation method.

Extend the existing export with raw prediction/explanation arrays, baseline and
method specifications, mapping, model/data identities, validation diagnostics,
assay context, decision timing, and an offline verification command. Verify
tampered/missing artifacts fail. A valid digest proves consistency with a recorded
manifest, not authenticity of a supplied assay or external timestamp.

Ensure `replay-read` renders saved bytes without inference. `replay-execute` must
create a new execution and compare outputs within declared tolerances. Do not
promise byte-identical regeneration from scripts that create new UUIDs/timestamps.

## 9. Multiuser and public-service work follows the local workflow

The existing Supabase code is a starting point for private uploads. It does not
make local reviews into a hosted multiuser system.

- Add tenant ownership to every review, prediction, explanation, artifact lookup,
  and export. Test two users, anonymous/expired sessions, and ownership changes.
- Exercise real database migrations, RLS/service-role boundaries, quota races,
  duplicate submissions, provider timeouts, persistence failure, and recovery.
  Existing three contract tests do not cover these properties.
- Inspect the migration set: it includes older portfolio tables as well as
  Concordia tables. Do not apply an unrelated schema history blindly to a new
  production database.
- Use durable raw input/output artifact storage with retention/deletion rules and
  a tested backup/restore path. A provider-response digest without retained bytes
  cannot reproduce the complete response.
- Keep public inference gated by verified service permission, an explicit budget,
  server-side quotas, and consent for sequence transfer. Do not enable a provider
  as part of implementing XAI or writing documentation.
- Implement submit/poll/cancel only if required by the chosen provider contract.
  Never report an HTTP 202 or queued job as completed. Avoid blind retries after
  uncertain completion or failed persistence.
- Load the structure viewer on demand and measure page performance. Current builds
  succeed with a large Molstar bundle; raising the warning limit is not a fix.

**Exit evidence:** tenant/concurrency/recovery integration tests, successful
authenticated end-to-end workflow on the intended deployment, and documented
operational limits. Fixture sessions are not evidence of email delivery.

## 10. Execution sequence and reviewable deliverables

| Order | Deliverable | Completion evidence |
| --- | --- | --- |
| 0 | Repository/CI/route/artifact repair | Clean-environment checks and green reviewed GitHub revision; existing behavior retained. |
| 1 | Scoped predictor and mapping contract | Upstream parity, invalid-input cases, measured resources, saved run and replay. |
| 2 | Model-sensitivity baseline and one XAI method | Exact target; controls; numerical diagnostics; explicit failures. |
| 3 | Review/structure/export integration | One full researcher task completed locally and an independently verified export. |
| 4 | Frozen multi-protein evaluation | Separate predictive, fidelity, and utility results with uncertainty and leakage accounting. |
| 5 | Researcher pilot | A researcher can reconstruct another person's decision; baseline task metrics and qualitative findings recorded. |
| 6 | Hosted multiuser release if needed | Real auth/storage/isolation/quota/recovery checks and a permitted operating budget. |

Keep each deliverable a reviewable change with its actual tests and remaining
limitations. Update the README/product overview after the corresponding behavior
exists. Do not mark future rows complete because schemas or mock tests exist.

Commands already used successfully in the audited local environment:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -ra
.venv/bin/ruff check .
.venv/bin/mypy --strict src/concordia/stability
.venv/bin/mypy src/concordia scripts/select_tsuboyama_domain.py scripts/build_tsuboyama_summary.py
node --test supabase/tests/protein-contract.test.mjs
npm --prefix frontend run check
npm --prefix frontend run build
npm --prefix frontend run build:stability
npm --prefix frontend test -- --config=playwright.local.config.ts
npm --prefix frontend test -- --config=playwright.public.config.ts
```

Run the workspace browser suite with isolated temporary state as well. Its current
default config reuses a fixed state directory; do not delete someone's existing
workspace to make a test pass. The audit ran the same eight tests with an external
temporary config. These commands validate the present environment, not a clean
install or a scientific claim. Do not rerun live-provider benchmark/deploy scripts
as a routine test gate.

## 11. Conditional structure-claim research track

If the intended first job is assessing predicted complexes, retain the current
structure verifier and make the research question: “Can specified independent
checks identify unreliable predicted interfaces at useful coverage?”

- First separate supplied-metric rule evaluation from provenance-backed claim
  verification. `verify_measurements` currently manufactures in-memory
  `recorded_real` envelopes from caller-supplied values. Those values do not prove
  a model run, experimental measurement, or authenticated source.
- Require stored sequence/structure/run artifacts and verified lineage before
  evidence is admitted as executed. Describe current support strengths as policy
  weights, not calibrated probabilities.
- Track shared weights/training sources when declaring model independence.
  Different model names or samples are not automatically independent evidence.
- Use repeated stochastic runs, matched random/noninterface perturbations, and
  fold-quality controls. The current all-paratope-to-alanine experiment cannot
  distinguish interface-specific effects from generic disruption on its own.
- Preserve the nine-complex benchmark's primary 0/9 result and secondary DockQ
  2/9 result with their different criteria. Document query-only alignments and
  sample-selection rules. Test real-MSA versus query-only conditions only within
  a separately budgeted protocol.
- Compare with confidence-only, geometry-only, and always-abstain controls using
  risk versus accepted coverage, with uncertainty and held-out threshold tuning.
- Do not claim a novel counterfactual protein explanation simply for adding a
  mutation sweep. Existing work includes ExplainableFold; compare the target,
  intervention, evaluation, and limitations explicitly.
  [ExplainableFold](https://arxiv.org/abs/2301.11765)

This is a separate experimental track. Structure agreement does not validate
stability, affinity, expression, or biological mechanism.

## 12. Instructions to the implementing engineer or agent

Read this plan, the audit, ADR-0004, the relevant source, and the nearest tests.
Recheck GitHub and the working tree before editing. Start with phase 0 and reuse
the existing review/evidence system. Preserve user changes and historical
artifacts. Implement one coherent end-to-end path before widening scope.

For every delivery report: identify files and behavior changed; commands and
results; exact model/data/protocol identities where relevant; unresolved failures;
and which claims are software-tested, actually executed, independently measured,
or biologically validated. Use “not evaluated” when evidence is absent.

The first convincing milestone is a researcher importing a protein mutation set,
inspecting a faithful explanation of a named prediction, recording a decision,
and handing another person a verifiable report. A subsequent frozen experiment
must establish whether that explanation and workflow are useful.
