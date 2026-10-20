# Concordia repository and scientific-product audit

Audit date: 2026-10-19. Purpose: establish what exists before writing the
[protein XAI build instructions](../protein-xai-build-instructions.md).

## Conclusion

Concordia has substantial working research-software infrastructure and a usable
local variant-review workflow. It also has a narrow measured-stability example
and structure-claim experiments. It does not yet demonstrate an end-to-end,
validated protein XAI method or a validated general protein-engineering product.

The strongest next step is to connect an exactly defined protein prediction and
tested explanation to the existing review, assay-import, and export workflow.
The main missing evidence is explanation fidelity and usefulness across proteins,
followed by researcher-task validation. More model endpoints alone will not
answer those questions.

## Scope and limits of this audit

- Inventoried and read bytes for all **332 first-party source/config files** in the
  selected tracked and nonignored working-tree scope: **51,274 lines**. Each file
  has an individual SHA-256 and local/GitHub comparison in the
  [TSV inventory](2026-10-19-file-inventory.tsv).
- Parsed all **270 local Python files** with Python AST, inspected module symbols
  and imports, and ran repository lint/type/test checks. Parsed all **250 Python
  files** in a downloaded GitHub-main archive as well.
- Compared each inventory file with live GitHub main and feature tree blob hashes.
  Read the published source differences and CI logs relevant to the findings.
- Manually traced the core researcher, model, explanation, evidence, structure,
  deployment, and data-evaluation paths. The inventory marks selected paths that
  received focused manual review. Other files received structural/static review
  and the applicable suite checks; this is **not a claim of line-by-line semantic
  verification of every file or exhaustive test coverage**.
- Read product/architecture/ADR/deployment documentation, dependency declarations,
  and selected recorded scientific reports. Dependency lock files were inspected
  as packaging artifacts; an offline `uv lock --check` passed.
- Excluded installed dependencies, caches, vendored/upload copies, generated
  builds, binary datasets/weights, and generated report HTML from the source count.
  The two excluded nonignored HTML outputs are `reports/demo.html` and
  `frontend/public/review-replay/report.html`. Selected data/results were checked
  separately; the large raw data corpus was not independently reanalyzed.
- No fresh package installation, wheel/container build, real Postgres migration,
  Deno check, live email/login flow, new hosted inference, or wet-lab validation
  was performed. Deno was unavailable. Browser provider paths used fixtures;
  the local stability browser path used the existing local engine.
- This task adds documentation and an audit inventory. It does not repair the
  findings, alter application source, deploy, commit, or push. Preexisting edits
  and untracked work were preserved. Test/build outputs are generated artifacts.

## Local and GitHub state

Repository: [srikarjy/concordia](https://github.com/srikarjy/concordia).

| Surface | Observed state |
| --- | --- |
| Local branch | `feature/antibody-boltz-concordia` |
| Local HEAD | `0cc262a`, “Add local variant review workbench with verifiable exports” |
| Previous local commit | `e93ca9c`, dependency/Space-import changes |
| GitHub feature HEAD | `65a44dcdab6abc561b66bfc2f1436ba853355110` |
| GitHub default/main HEAD | `cad99ff32a3f87009ca889ec4e2fb48f14295b9b` |
| Remote branch relationship | Feature is 6 commits ahead and 5 behind main; common ancestor `fbba3b8aa41079dfd256d602e6c0df74b30c2852`. |
| Local versus feature | Two additional local commits plus modified and untracked files. |
| Inventory versus main | 272 identical, 12 different, 48 absent from main. |
| Inventory versus feature | 273 identical, 11 different, 48 absent from feature. |
| Pull requests / issues | Four PRs returned, all merged; no open PRs. No issues returned by the all-state issue query. |
| Branch protection | API reported main and feature unprotected. |
| Latest feature CI | [Failure, run 39081022425](https://github.com/srikarjy/concordia/actions/runs/39081022425). |
| Latest main CI | [Failure, run 39080314624](https://github.com/srikarjy/concordia/actions/runs/39080314624). |

Both latest CI logs show Python collection failing on missing `torch`, and the
frontend test server failing on missing `Bio`. The local environment contains
dependencies not supplied by those published installation paths. A green local
suite therefore does not establish a green fresh clone or a green GitHub release.

Untracked work includes the HF structure/stability deployment directories,
Supabase functions/migrations, the public protein-upload UI, structure inspection,
review-replay assets, static-build scripts, and associated tests. Modified files
include frontend configuration and entrypoints, stability structure helpers,
deployment configuration, and local runtime documentation. This audit does not
relabel those preexisting changes as newly implemented work.

## What is built

| Area and source | Actual capability | Boundary |
| --- | --- | --- |
| [Local review](../../src/concordia/review/workflow.py), [API](../../src/concordia/api/reviews.py), [UI](../../frontend/src/review-main.tsx) | Reference validation; candidate/score imports; selected/excluded/deferred decisions with reasons; protected-site overrides; revision conflicts; assay import with decisions-at-import; HTML/CSV/ZIP export. | Writable API is loopback-only. Imported evidence authenticity is not independently established. No connected protein-attribution layer. |
| [Frozen stability](../../src/concordia/stability/measured.py), [request](../../src/concordia/stability/request.py), [ranker](../../src/concordia/stability/ranker.py) | Existing 1IGV candidate scores, calibrated example intervals, protected-site/OOD/multi-mutant refusals, typed request and ledger records. | Specific frozen dataset. Cannot score arbitrary uploaded proteins; intervals do not transfer automatically. |
| [Protein uploads](../../frontend/src/protein-workbench.tsx), [Supabase handler](../../supabase/functions/protein-workbench/index.ts) | Verified-user private uploads, per-user analyses/runs, quota reservations, optional Boltz/OpenFold requests. | General uploads are 20–300 residues; local review supports 20–3000. Public inference defaults off. Current checks do not prove live auth, RLS, race safety, or email delivery. |
| [Structure workflow](../../src/concordia/runtime/structure_workflow.py), [inspection UI](../../frontend/src/structure-inspection.tsx) | Authenticated composition of existing stability and structure services; refusal propagation; cached artifacts. | HTTP/provider execution is separate from stability evidence and biological validation. Multiple gateway paths need clear ownership. |
| [Events](../../src/concordia/events/sqlite.py), [artifact store](../../src/concordia/storage/content.py), experiments | Durable local event/run records, hashes, experiment nodes, provenance, artifact lookup and export. | Local integrity checks are not external attestation or proof of measurement authenticity. Durability depends on the actual deployment backend. |
| [Campaigns](../../src/concordia/campaigns/service.py), [Postgres adapter](../../src/concordia/campaigns/postgres.py), [assay importer](../../src/concordia/campaigns/assay.py) | Campaign/round/candidate/measurement contracts; authorization primitives; recommendations; reporting; study and replay records. | These modules are not evidence of one complete hosted researcher journey or a scientifically validated learning loop. |
| [Structure verifier](../../src/concordia/verification/structure_rules.py), [cross-verifier](../../src/concordia/verification/cross.py) | StructureScope, physical/sample/second-model/counterfactual/reference rules; provenance traversal; deterministic statuses. | Policy thresholds/strengths are not learned probabilities. Supplied-metric entrypoint has a provenance gap described below. |
| [Molecular explanations](../../src/concordia/explanations/tree_shap.py) | TreeSHAP for the molecular fingerprint baseline with additive reconstruction checks. | Molecular features, not protein residues or the protein stability predictor. |
| Genomic attribution and [Evo2 worker](../../deploy/hf-evo2-worker/app.py) | Separate DNA-scoring/attribution integration and protocol/evidence infrastructure. | Does not establish protein-model explanations or support transfer of genomic validation claims. |
| [Local-language schema](../../src/concordia/stability/nl_schema.py) | Constrained interpretation of user requests and deterministic output contracts. | Parsing or prose generation is not a mechanistic explanation. |
| Colonies, scientific tools, virtual-cell adapters | Bounded execution, registries, study/protocol contracts, recorded/fixture workflows. | Preserve software; these are separate scientific tasks. The local execution adapter is for trusted built-in tools, not arbitrary hostile code. |

The review path is more complete than older documentation suggests: importing
assay outcomes and exporting a verifiable report are already implemented locally.
Conversely, current uploads and impressive 3D displays do not imply generalized
stability scoring or protein XAI.

## Findings that determine implementation order

### F1 — High: published installation and CI do not reproduce the local pass

Evidence: [CI workflow](../../.github/workflows/ci.yml),
[uncertainty script](../../scripts/evaluate_tsuboyama_uncertainty.py),
[predictor script](../../scripts/evaluate_tsuboyama_predictor.py), and the linked
live CI logs. Lightweight uncertainty tests transitively import Torch/Transformers.
CI omits the local `esm` profile. Published frontend dependencies omit `Bio`.

Action: separate lightweight imports from model execution; define and test each
environment; publish reviewed dependency fixes only after fresh-install checks.
Do not infer that installing one missing dependency resolves every subsequent
clean-environment failure.

### F2 — High: declared model pins are not always enforced

Evidence: `evaluate_tsuboyama_predictor.py` declares `CHECKPOINT_COMMIT` and writes
it into artifacts, but loads tokenizer/model without `revision=...`.
[Baseline extraction](../../scripts/evaluate_tsuboyama_baselines.py) and
[runtime model loading](../../src/concordia/runtime/model_registry.py) also need
resolved-revision checks.

Action: enforce actual revisions, verify weight identities, and invalidate/rebuild
artifacts whose declared identity cannot be linked to what was loaded. This is a
reproducibility gap, not proof that a different weight version was actually used.

### F3 — High: metric-rule evaluation can imply provenance it did not verify

Evidence: `structure_rules.verify_measurements` wraps supplied numbers in
temporary `recorded_real`, `scientific_use_allowed=True` provenance envelopes;
the source payload contains a complex ID rather than the actual sequence/run.
The [API handler](../../src/concordia/api/workspace.py) returns the resulting
eligibility flag. `verify_claim` sets it true for a supported status.

Action: distinguish “rules applied to supplied values” from authenticated,
artifact-backed verification. Require retained source/execution references for
the latter. Add regression tests preventing supplied values from self-certifying
execution or biological validity. Preserve backward compatibility through an
explicit contract/version change.

### F4 — High for XAI: ranking, prediction, and explanation targets differ

Evidence: rank-average ThermoMPNN/one-hot ordering in `stability/ranker.py`;
ESM-feature ridge predictions and intervals in `stability/measured.py`; molecular
TreeSHAP and genomic attribution elsewhere. There is no connected protein XAI
target/method/validation record.

Action: specify a scalar output and its predictor for every explanation. Preserve
component ranks/cohort/ties when explaining ranking. A score-policy trace and a
protein-model attribution are different artifacts.

### F5 — High for new-protein claims: current evaluation scope is narrow

Evidence: frozen 1IGV table; within-domain holdout; 152 evaluated holdout rows;
the upstream-overlap check in `evaluate_structure_aware.py` searches split IDs for
`1IGV`. It does not establish homolog/family separation. Upstream model training
and Concordia model selection are distinct leakage surfaces.

Action: use the existing result as a regression/example. Freeze new-protein/family
evaluation and record known/unknown training exposure. Do not transfer calibration
or present fold SDs as significance tests.

### F6 — Medium/high: serving reconstructs mutable calibration and trusts local artifacts

Evidence: `MeasuredStabilityEngine.__init__` loads joblib, Parquet, tables, and
uncertainty; validates selected identities but not a complete artifact manifest;
recomputes T2 calibration and writes a fixed output path. Several assets are
ignored locally and copied by the stability Dockerfile.

Action: precompute/version calibration, verify all trusted model/data artifacts
before loading, use explicit roots, and provide a clean-machine asset path.

### F7 — Medium: public build does not deliver the local review application

Evidence: [Vercel config](../../vercel.json) builds `dist-stability` and rewrites
`/` to `stability.html`; [Vite stability config](../../frontend/vite.stability.config.ts)
contains one entrypoint. The stability page's review link uses `/`. Replay files
in `public/` do not add the review React application to that build.

Action: select intended routes and build entries, then test production navigation.
The six public tests currently pass without detecting this missing journey.

### F8 — Medium: deployment and documentation describe different products/states

Evidence: historical genomic/colony descriptions, generic audit-layer README,
new local review, frozen stability UI, owner HF gateway, and separate Supabase
gateway. README's “no network calls” static-page wording is too broad for the
current optional authenticated/upload/scoring actions. The runtime registry
contains historical smoke-test labels and a ThermoMPNN-residency description that
does not describe fresh inference in the frozen scoring service.

Action: one product overview with explicit runtime modes; precise deployment
ownership; dated execution evidence; capabilities derived from actual adapters.

### F9 — Medium: public-service tests cover contracts more than operations

Evidence: three Supabase contract tests exercise input and response parsing.
No real database/RLS/race test or Deno typecheck was run here. Hosted output
records contain a digest of the provider response but not its complete raw bytes.

Action: test real persistence/isolation/concurrency/recovery; retain permitted raw
artifacts for replay; verify actual auth flow before claiming multiuser readiness.

### F10 — Lower priority: maintainability and frontend size

`api/workspace.py` has 2,847 lines; campaign service and Postgres adapter exceed
1,500 each. Frontend builds warn about a large Molstar chunk and the broader build
also warns about legacy 3Dmol eval. Whole-tree mypy fails on duplicate `app`
modules and is nonblocking in CI.

Action: clarify boundaries and checks as touched, lazy-load large views, and keep
refactors targeted. A broad rewrite is not needed to implement the first XAI path.

## Scientific results inspected, not rerun

| Recorded result | What the artifact says | Appropriate interpretation |
| --- | --- | --- |
| `data/processed/tsuboyama_uncertainty_metrics.json` | Normalized holdout interval covers 143/152 rows (94.08%); mean width 4.6734 kcal/mol across eight held-out positions. | A recorded within-1IGV result with wide intervals; not a per-candidate success probability or new-protein guarantee. |
| `reports/boltz2-antibody-benchmark-nim-defaults.json` | Nine complexes; 3 recycles, 50 steps, 5 samples; original criterion 0/9; secondary acceptable-or-better DockQ 2/9. | Criterion-dependent, small retrospective benchmark with query-only alignment. Not a universal claim about Boltz-2. |
| `reports/verifier-on-boltz-benchmark.json` | Two correct and seven incorrect reference labels; zero supported, eight partially supported, one contradicted; zero false passes, two false fails. | No demonstrated acceptance utility at this setting. Compare with always abstaining and evaluate risk versus coverage. |
| `reports/structure-null-baseline-benchmark.json` | TP=2, TN=1, FP=6, FN=0; specificity 1/7. | Geometry plausibility is a weak discriminator on this small set. It is not an independent learned structure predictor. |

These local report paths are not all committed/distributed with a clean clone.
The evidence snapshot records their digests. They were inspected as historical
artifacts; provider execution, raw-response authenticity, and experimental labels
were not independently re-established in this audit.

The all-paratope-to-alanine counterfactual also needs matched disruption controls
and repeated runs before a claim of interface-specific biological importance.
Rule-pack numerical strengths are policy choices, not calibrated confidence.

## Validation run in this audit

| Check | Observed result |
| --- | --- |
| Full local Python suite | **520 passed**, two dependency deprecation warnings, 45.75 s. Includes review export verification and tamper rejection. |
| Ruff repository check | **Passed**, zero findings under configured exclusions. |
| Strict stability mypy | **Passed**, seven source files. |
| Main package + selected scripts mypy | **Passed**, 157 source files. |
| Whole-tree `mypy .` | **Failed**: duplicate `app` modules across deployment directories; check stops there. |
| Frontend TypeScript | **Passed**. |
| Workspace build | **Passed**, visualization warnings noted above. |
| Stability build | **Passed**, large-chunk warning. |
| Workspace Playwright | **8 passed**, isolated temporary state. |
| Local researcher/stability/replay Playwright | **3 passed**. |
| Public-page Playwright | **6 passed**, local preview/fixture service paths. |
| Supabase Node contract tests | **3 passed**. |
| Offline UV lock consistency | **Passed**, 126 packages resolved; isolated cache. |
| Local / GitHub-main Python AST | **270 / 250 passed**. |

The first local browser attempt was blocked by sandbox socket-binding permission;
it passed when rerun with the required local-server permission. Initial UV cache
access was similarly blocked; an isolated temporary cache succeeded. These were
environment restrictions, not application failures. Neither approval involved
deployment or paid inference.

Raw audit logs and the downloaded GitHub source are in the local temporary
directory `/private/tmp/concordia-review-20261019`. Portable facts, artifact/log
digests, commands, and results are retained in
[the evidence snapshot](2026-10-19-evidence.json). Temporary files are not a durable
release artifact; copy/reproduce them deliberately if a later review needs them.

## Recommendation

Keep the research ambition, narrow the first task, and build on the existing
review workflow. First repair reproducibility and provenance. Then deliver one
protein predictor/explanation pair with meaningful controls, put it in the
researcher's decision/export journey, and evaluate it on a frozen multi-protein
study. The resulting contribution could be a credible research tool and XAI
evaluation system. Novel-method or biological-mechanism claims need additional
evidence beyond this repository audit.
