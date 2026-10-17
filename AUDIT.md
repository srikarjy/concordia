# Concordia Repository Audit

Audit date: 2026-10-16
Repository: /Users/srikarjy/resume_projects/concordia
Mode: read-only audit. No source, test, configuration, or architecture changes were made. The only file written by this audit is this report.

## Executive finding

Concordia is a substantial, test-rich scientific-software prototype with a working local FastAPI workspace, durable run API, campaign persistence/contracts, model-provider adapters, frontend workspace, provenance artifacts, and explicit non-scientific evidence boundaries.

The most important gap is architectural: the new measured-protein stability contracts exist and are unit-tested, but they are not connected to the campaign training/design path. The reachable protein baseline still uses synthetic hydrophobic-fraction labels. That path marks itself non-scientific, but it remains the active protein-training route and can still produce selected candidates. The repository demonstrates orchestration and safety contracts more strongly than a real measured protein-design loop.

Verification is mixed:

- Full Python pytest: 373 passed, 1 skipped, 2 warnings.
- CI-equivalent mypy passes on 143 source files, but does not cover all tests/scripts.
- Whole-repository project-config mypy fails with 67 errors in 22 files.
- mypy --strict src/ fails with 75 errors in 9 files.
- Whole-repository Ruff fails with 55 errors. CI only runs Ruff on src and tests.
- Frontend Playwright was attempted locally and could not start its web server because this environment rejected binding to 0.0.0.0:7861. This is locally unverified, not proof CI fails.

## 1. Inventory

### 1.1 Repository tree

The complete source/configuration tree captured at audit time is included in the inventory appendix below. The requested exclusions were applied for .git, .venv, __pycache__, node_modules, and data. Generated content-addressed leaves under .concordia/ and artifacts/ are summarized rather than expanded as source files.

Generated/runtime state:

- .concordia/: approximately 2.0G. It contains SQLite ledgers, content-addressed artifacts, external Evo2 and State checkouts/caches, local Qwen/OpenRouter qualification runs, NVIDIA smoke artifacts, workspace state, and sample renders.
- artifacts/: approximately 64M, including baseline model artifacts and packet/SHAP outputs.
- frontend/dist/: approximately 1.0M, compiled browser assets.
- A local credential file exists at .concordia/nvidia-api-key, mode 0600, 70 bytes, ignored by Git. Its value was not read or copied into this report.
- The vendored .concordia/external/evo2-source/ contains its own Git checkout and source tree. It is not part of the installable Concordia package.

Files over 500 lines:

| File | Lines | Assessment |
|---|---:|---|
| src/concordia/api/workspace.py | 2,647 | Large application composition/API module; highest integration concentration. |
| src/concordia/campaigns/service.py | 1,582 | Large SQLite campaign service/business-state module. |
| src/concordia/campaigns/postgres.py | 1,526 | Large Postgres implementation of the campaign store contract. |
| tests/unit/test_campaigns.py | 1,211 | Broad campaign contract/integration-style unit coverage. |
| tests/integration/test_campaign_api.py | 627 | Campaign API coverage. |
| tests/unit/test_cellforge.py | 509 | Tool/runtime security and execution tests. |
| frontend/src/App.tsx | 994 | Single-file frontend composition for all workspace views. |
| uv.lock | 1,836 | Dependency lockfile, not application logic. |
| frontend/package-lock.json | 1,407 | Frontend dependency lockfile. |

### 1.2 Top-level packages under src/concordia

Inbound-reference counts are from a static import scan across src, scripts, and tests. Dynamic imports and shell invocations cannot be fully proven statically.

| Package | What it does | Inbound status |
|---|---|---|
| antibody | Antibody/nanobody request schemas and normalization. | Tools and antibody tests. |
| api | Durable run API and scientific workspace FastAPI applications. | CLI, local launcher, integration tests, frontend deployment path. |
| benchmarks | Throughput, replay, claim-verifier, and Boltz benchmarks. | CLI and benchmark tests. |
| campaigns | Campaign schemas, SQLite/Postgres stores, assays, constraints, model jobs, reports, workers, validation. | Workspace API, sample E2E, campaign tests. |
| cellforge | Local bounded tool execution, registry, policy, service boundary. | CLI, scientist runtime, colonies, tests. |
| colonies | Deterministic/local-Qwen colony scheduling, execution, lineage, persistence. | API, CLI, reporting, tests. |
| evaluation | Colony/model fitness and comparison functions. | Colony execution/schema and tests. |
| events | SQLite event ledger and hash-chain persistence. | API, runtime, CLI, tests. |
| evidence | Evidence packet construction and schemas. | CLI, scientist prompt/session, interventions, tests. |
| experiments | Experiment DAG schemas and service operations. | Workspace API, benchmarks, tests. |
| explanations | TreeSHAP generation and validation. | CLI directly; no workspace route found. |
| genomes | Mutation genomes and schemas. | Colonies, benchmarks, tests. |
| genomics | Evo2, Boltz, OpenFold2, ProteinMPNN, RFdiffusion, gateways, queues, schemas, rate limits. | API, campaigns, CLI, scripts, tests. |
| graph | Provenance graph schemas and graph construction. | Ingestion, cellforge, runtime, scientist, tests. |
| ingestion | Project discovery, parsing, indexing, provenance graph ingestion. | CLI, CellForge, tests. |
| interventions | Packet transformation/intervention utilities. | Static inbound reference is test-only. |
| predictors | Baseline data download, features, model training, splitting, fingerprints. | CLI, explanations, tests. |
| reporting | Saved workspace/report demos and colony report assembly. | API, CLI, tests. |
| runtime | Durable run state machine, services, workers, contracts, replay. | API, CLI, colonies, tests. |
| scheduling | SQLite job leases and concurrency/rate-limiting support. | Runtime, API, scientist qualification, tests. |
| scientific | Framework catalog, study protocols, extension contracts, evidence boundaries. | API/genomics, tests. |
| scientist | Ollama/Qwen, optional llama.cpp/OpenRouter adapters, prompts, records, qualification, tools. | CLI, colonies, reporting, tests. |
| stability | Sign-safe ΔΔG wrappers, wild-type anchoring, canonicalization, write-once manifests. | Selector, package exports, tests only. |
| storage | Content-addressed artifact storage and integrity reads. | Widely referenced. |
| tools | Builtin tool definitions and registry exports. | CellForge registry, tests. |
| verification | Cross-verification, structure rules/baselines, measurements, backtracking. | API, benchmarks, reporting, runtime, scripts, tests. |
| virtual_cell | CELLxGENE ingestion, State contracts, sandbox, source/release verification, demos. | CLI and virtual-cell tests. |

### 1.3 Scripts

| Script | Role | Inbound-reference status |
|---|---|---|
| antibody_dockq.py | DockQ/interface scoring helper. | benchmark_antibody_complexes.py; also manual CLI. |
| benchmark_antibody_complexes.py | Antibody complex benchmark driver. | update_readme_benchmark.py; manual CLI. |
| benchmark_structure_null.py | Geometry-only structure null baseline driver. | Unit test; manual CLI. |
| build_tsuboyama_summary.py | Parses normalized Tsuboyama variants and builds domain summaries. | No inbound source/test import; manual data-preparation CLI. |
| design_binder.py | Binder-design/structure pipeline driver. | No inbound source/test import; manual CLI. |
| paratope_counterfactual.py | Paratope selection/counterfactual structure helper. | Script-import tests; manual CLI. |
| render_sample_report.py | Renders the crambin HTML sample. | Manual CLI only. |
| run_sample_e2e.py | Runs the synthetic crambin experiment/API/structure sample. | Manual CLI only. |
| score_complex_against_crystal.py | Legacy one-off complex scoring script. | Legacy exclusion in script-import tests; executes work at import time. |
| select_tsuboyama_domain.py | Selects a qualifying domain and freezes its stability manifest. | Stability tests; manual CLI. |
| serve_local.py | Starts the workspace and optionally loads local NVIDIA/HF credentials. | Manual launcher only. |
| ship_check.sh | Release/deployment checks. | Manual shell entry point. |
| structure_measurements.py | Computes physical structure measurements. | API/workspace, scripts, tests. |
| update_readme_benchmark.py | Updates README from antibody benchmark outputs. | Manual CLI. |
| verify_benchmark.py | Verifies benchmark reports/provenance. | paratope_counterfactual.py; manual CLI. |

No application module, class, or function was marked as certainly dead solely from static inbound-reference scanning. Manual CLI scripts are unreferenced by Python imports by design, not necessarily dead. Referenced-only-by-tests candidates include concordia.interventions, benchmark_structure_null.py, paratope_counterfactual.py, and most of the stability path except its manual selector.

### 1.4 Entry points

Installed entry point: pyproject.toml:40-41 exposes concordia = concordia.cli:main.

CLI subcommands: download, train-baseline, explain, validate-explanations, build-packets, demo, doctor, genomic-demo, serve-api, serve-workspace, ledger, run-worker, ingest-project, list-tools, qualify-scientist, qualify-openrouter, colony-demo, qwen-colony-demo, cellxgene-state-demo, verify-state-checkout, verify-state-release, verify-evo2-source, nvidia-evo2-smoke, bionemo-preflight, benchmark.

FastAPI applications:

- src/concordia/api/app.py:create_app: durable run/control-plane API.
- src/concordia/api/workspace.py:create_workspace_app: workspace, campaign, experiment, NVIDIA, colony, reporting, framework API.

Durable API routes:

- POST /runs
- GET /runs/{run_id}
- POST /runs/{run_id}/replay
- POST /runs/{run_id}/cancel
- GET /runs/{run_id}/events
- GET /runs/{run_id}/artifacts
- GET /ledger/export
- GET /runs/{run_id}/stream
- GET /health
- GET /ready

Workspace route families:

- Readiness/workspace: /api/capabilities, /api/connectors/health, /health, /ready, /privacy, /api/workspace, /api/artifacts, /api/artifacts/{digest}, /api/graph, /api/events, /api/stream, /api/report.
- NVIDIA/model: /nvidia/evo2/generate, /nvidia/evo2/forward, /nvidia/evo2/forward/{job_id}, /nvidia/evo2/attribute, /nvidia/evo2/attribute/{job_id}, /nvidia/openfold2/predict, /nvidia/boltz/predict, /nvidia/boltz/complex.
- Colony: /colony/run.
- Campaign: /campaigns and all nested campaign, round, candidate, evidence, report, measurement, constraint, assay, model-run, model-job, dataset, study, validation, recommendation, and artifact routes.
- Experiment DAG: /experiments and nested node, candidate, compare, Evo2, and Boltz routes.
- Structure verification: /v1/structure-claims/verify and /v1/structure-claims/baseline.
- Metadata: /.well-known/concordia-tools.json, /api/tools, /api/frameworks, /api/tools/openapi.json.

The decorator scan found 86 route decorators total across the two FastAPI modules.

Background workers and scheduled work:

- concordia run-worker starts concordia.runtime.worker.LocalWorker, which claims durable leases and processes scheduled runs.
- create_workspace_app constructs CampaignModelWorker; the model-job run route executes one job synchronously through that worker.
- Evo2 forward and attribution use FastAPI BackgroundTasks after submission.
- Colony scheduler uses bounded ThreadPoolExecutor workers per generation.
- Recovery exists for stale/scheduled durable jobs, but no independently configured cron/scheduler process was found. “Scheduled” means persisted state/worker polling, not a deployed external scheduler.

## 2. What is actually wired together

| Thread | Reachability | Tests | Stability/sign assumptions |
|---|---|---|---|
| Campaigns | Reachable from workspace routes around workspace.py:1293; model jobs use CampaignModelWorker around lines 607-611 and 1906-1921. | Campaign API and unit tests run. | training.py:165-175 uses composition features including hydrophobic fraction; it is not connected to stability/. |
| Durable runtime/workers | Reachable from serve-api, run-worker, and run API. | Runtime, worker, API, ledger, security tests run. | No ΔΔG assumption found. |
| Virtual-cell configs | Reachable from cellxgene-state-demo and source/release verification commands. | Virtual-cell ingestion/release/source/config tests run. | Separate cell/state evidence family. The demo uses a recorded fixture runner and does not execute State weights. |
| Structure baseline | Reachable from POST /v1/structure-claims/baseline and benchmark_structure_null.py. | Structure baseline/rules tests run. | Geometry-only antibody control, not protein ΔΔG. |
| Stability contracts | Reachable only by package imports, unit tests, and manual Tsuboyama scripts. No API/CLI/campaign/frontend path consumes the manifest. | 13 stability tests run. | Internal convention is explicit in contracts.py:15,30-56. No frozen domain manifest exists. |
| Generate view | Reachable in React view generate; calls hosted Evo2, forward, attribution, OpenFold2, and Boltz routes. | Backend fail-closed tests run. Frontend Playwright was locally blocked at server startup. | Hosted outputs remain computational/non-scientific. |
| API layer | Both APIs reachable via CLI/uvicorn and FastAPI TestClient. | Full Python suite passes. | Campaign/experiment mutations use scoped tokens; interactive NVIDIA uses per-client rate limiting. |
| BioNeMo | Only configured through private endpoint/key environment variables or injected tests. | Connector/preflight/model-job tests use fake clients/runners; no live service verified. | Artifact-only private-service contract; no deployed /healthz, /train, /infer service in repo. |
| Ollama/Qwen | Reachable through doctor, qualify-scientist, qwen-colony-demo, and local scientist runtime. | Adapter/qualification/colony tests run, but do not prove a live daemon/model. | Natural-language/tool layer; does not train or score protein properties. |
| BioRender | No native connector/import API. campaigns/reporting.py:41 emits concordia-biorender-manifest-v1; workspace.py:777-780 reports not_installed. | Manifest tests run. | Serialization/export boundary only. |

ΔΔG-like/sign landmines outside src/concordia/stability/:

- campaigns/training.py:165-175 computes hydrophobic fraction and other composition features. It is not named ΔΔG, but it is the active protein baseline and main synthetic-label landmine.
- run_sample_e2e.py:99-132 trains/selects against synthetic hydrophobic-fraction labels.
- render_sample_report.py:48-50 describes a selected Cys16→Ala candidate from synthetic labels.
- verification/measurements.py:37-53 uses “stability” for repeated measurement/assay summary, not protein folding stability.
- No external FoldX/Rosetta/ThermoMPNN ΔΔG adapter was found outside stability/. The only explicit conversion is contracts.py:49-56.

## 3. Verification gates — what is really enforced

CI workflow: .github/workflows/ci.yml has one Python job and one frontend job.

Python job:

1. Pinned checkout/action setup.
2. uv sync --extra dev --extra virtual-cell --extra postgres.
3. .venv/bin/pytest -q.
4. .venv/bin/ruff check src tests.
5. .venv/bin/mypy src/concordia scripts/select_tsuboyama_domain.py scripts/build_tsuboyama_summary.py.
6. .venv/bin/mypy --disallow-untyped-defs src/concordia/stability scripts/select_tsuboyama_domain.py scripts/build_tsuboyama_summary.py.
7. UV_CACHE_DIR=/tmp/uv-cache uv build.

Frontend job:

1. Node 22.
2. uv sync --project ..
3. npm ci.
4. npm run build.
5. npx playwright install --with-deps chromium.
6. npm test.

Actual scope:

- Ruff does run in CI, but only on src and tests. It does not lint scripts, deploy, frontend TypeScript, docs, or configuration.
- Project-config mypy checks all src/concordia plus only two stability scripts. It does not type-check the rest of scripts, deploy, or tests.
- disallow_untyped_defs applies only to the stability override list and its explicit CI target.
- pytest uses testpaths = ["tests"] and runs the full Python tree subject to skips. It does not run frontend tests.
- uv build checks package buildability, not live provider availability or scientific validation.
- No CI job performs live NVIDIA, BioNeMo, Ollama, BioRender, or scientific validation.

Current skip:

tests/unit/test_scripts_import.py:21 skips the entire module if Biopython is unavailable, with reason “scripts need biopython, which is not a project dependency.” This removes script-import discovery plus structure_measurements/paratope helper E2E coverage.

Conditional but not skipped in this environment:

tests/unit/test_cellxgene_ingestion.py:161-163 uses importorskip for anndata/numpy/pandas. The virtual-cell extra is installed locally, so it ran here; a CI environment without that extra would lose that branch.

Success-without-intended-work risks:

- CI mypy success on 143 files omits most scripts, tests, and deploy code.
- Mypy is not strict globally; unannotated functions outside the stability override are accepted.
- A missing Biopython dependency turns operational script failures into a skipped test module.
- select_tsuboyama_domain.py uses cast(Any) at its parse boundary; runtime int() validation exists, but static checking cannot prove the input shape.
- Provider tests mostly inject fake clients/runners and do not establish live provider behavior.
- Passing models deliberately set scientific_use_allowed=False, so tests prove boundaries rather than biological truth.
- Provider parsing assertions execute only after the relevant response branch is reached; no CI live-provider evidence was found.

## 4. Current state of the three verification commands

Commands were run from the repo root on 2026-10-16. Failures did not stop later commands.

The verbatim outputs are inserted below:

### Whole-repository Ruff

Command: .venv/bin/ruff check .

Exit status: 1.

### Mypy with project config

Command: .venv/bin/mypy .

Exit status: 1.

### Mypy strict on src

Command: .venv/bin/mypy --strict src/

Exit status: 1.

### Full pytest

Command: PYTHONPATH=src .venv/bin/pytest -o addopts='' -q -ra

Exit status: 0.

Final summary: 373 passed, 1 skipped, 2 warnings in 22.33s.

## 5. Risk register

Sorted by severity:

| Location | Issue | Severity | Classification |
|---|---|---|---|
| .github/workflows/ci.yml:20 | CI Ruff excludes scripts even though whole-repo Ruff reports 55 errors. | High | Verification gap |
| .github/workflows/ci.yml:21-22, pyproject.toml:58-63 | CI mypy is not whole-repo strict; broader checks find 67/75 errors. | High | Verification gap |
| src/concordia/campaigns/training.py:165-175 | Reachable protein-training baseline uses composition features including hydrophobic fraction instead of measured stability labels. | High | Correctness/design concern |
| scripts/run_sample_e2e.py:99-132 and scripts/render_sample_report.py:48-50 | Visible end-to-end protein sample trains/selects from synthetic labels. | High | Correctness/design concern |
| src/concordia/stability/ and scripts/select_tsuboyama_domain.py | Measured ΔΔG contracts are not reachable from API, CLI, campaign connector, or frontend; no frozen manifest exists. | High | Integration gap |
| tests/unit/test_scripts_import.py:21 | Missing Biopython skips the entire script import/helper E2E module. | High | Verification gap |
| src/concordia/api/workspace.py:777-780 and src/concordia/campaigns/reporting.py:34-42 | BioRender is a manifest format only; no native connector/import/render verification. | Medium | Design concern |
| src/concordia/api/workspace.py:575-605 and src/concordia/campaigns/connectors.py:126-270 | BioNeMo is only a private HTTP adapter; no live deployment/model execution verified. | Medium | Integration/verification gap |
| src/concordia/api/workspace.py:738-780 | Connector health reports last_success unknown and marks Ollama configured from a default loopback URL without proving daemon/model usability. | Medium | Verification gap |
| src/concordia/campaigns/reporting.py:152-154 | BioRender manifest digest uses default=str, weakening canonical provenance semantics. | Medium | Provenance/design concern |
| frontend/playwright.config.ts:7-12 | Local Playwright server binding failed in this environment before browser tests ran. | Medium | Environment/verification gap |
| scripts/select_tsuboyama_domain.py parse boundary | cast(Any) suppresses static information at the position parser. | Medium | Verification/type-safety gap |
| src/concordia/campaigns/postgres.py:256 and callers | Untyped _connect causes repeated strict-mypy no-untyped-call errors. | Medium | Verification/type-safety gap |
| workspace.py and campaigns/service.py | Large modules concentrate routing, persistence, provider wiring, authorization, reporting, and untyped functions. | Medium | Design/maintainability |
| .concordia/nvidia-api-key | Local credential material is present in ignored runtime state; safe file mode exists, but no external secret manager. | Medium | Security/environment concern |
| src/concordia/scientific/frameworks.py:46-63 | Framework catalog says RFdiffusion/ProteinMPNN planned while code/connectors/tests exist elsewhere; readiness semantics can be confusing. | Low | Design/documentation |
| src/concordia/verification/measurements.py:37-53 | “Stability” naming collides with protein folding stability. | Low | Naming/design |
| src/concordia/api/app.py:44 and workspace.py:787-989,2615-2626 | Strict mypy reports missing route/middleware return annotations. | Low | Verification/type-safety |
| scripts/score_complex_against_crystal.py:1-8 | Legacy script executes at import time and is excluded from script-import tests. | Low | Legacy/dead-code verification gap |
| requirements-space.txt | Deployment lock intentionally omits many optional/model/script dependencies; broad CLI use in the Space will not work. | Low | Environment/design |

## 6. Dependency and environment facts

Observed interpreters:

- System Python: 3.12.2.
- Project virtualenv Python: 3.13.12.
- Host: macOS Darwin 25.6.0, ARM64, Apple Silicon M2 MacBook Air.
- Declared range: >=3.11,<3.14.

Declared core dependencies in pyproject.toml: FastAPI, gradio_client, httpx, joblib, numpy, pandas, pydantic, PyYAML, RDKit, scikit-learn, uvicorn.

Optional extras: SHAP (xai), Ollama (scientist), llama-cpp-python (llama), AnnData (virtual-cell), psycopg (postgres), and developer tooling.

Static imports not declared as core dependencies:

- Bio/Biopython, the reason the script-import test skips.
- huggingface_hub, imported by scripts/serve_local.py.
- torch, imported by Evo2/worker-related code.
- gradio and spaces, imported by the separate HF worker.
- evo2, scoring, qualification, and structure_measurements, which are local/vendor/deploy module boundaries.
- anndata, psycopg, ollama, llama_cpp, and shap are optional-only and fail/skip if the extra is absent.

CI/M2 differences:

- CI installs dev + virtual-cell + postgres, not scientist, xai, llama, or Biopython.
- CI is Ubuntu; local is macOS ARM64. RDKit, PyTorch, llama.cpp, and other binary wheels may behave differently.
- MPS/CUDA behavior is not tested; no local ESM/ESM-2 embedding/training pipeline is present.
- Docker/Space installs requirements-space.lock.txt, not full pyproject extras, and intentionally excludes model weights/Ollama/BioNeMo/Biopython.
- Frontend CI uses Node 22 and Chromium. Local Playwright startup was blocked by the environment’s bind restriction.

## 7. Open questions

1. Should the next milestone replace campaigns/training.py and the crambin sample with frozen Tsuboyama measured-ΔΔG, or retain synthetic data only as a separate demo?
2. Which exact Tsuboyama domain, raw file, normalization command, and manifest should be frozen?
3. Should the stability selector become a first-class CLI/API/campaign operation?
4. Is BioRender intended to be a real authenticated connector, a downloadable manifest format, or both?
5. What BioNeMo endpoints, service identities, model versions, and artifact stores are intended?
6. Should the public workspace remain unauthenticated for demo routes while mutation routes use scoped tokens?
7. Should CI install Biopython and execute all script-import tests?
8. Should CI lint/type-check all scripts and deploy code?
9. Which Python version is the release target?
10. Must the local NVIDIA key move to an external secret manager before shared deployment?
11. Should Playwright server binding be made compatible with restricted local environments?
12. Should repeated-run “stability” be renamed to avoid confusion with folding stability?

## Appendix A — inventory tree

The source/configuration inventory output follows.

./.DS_Store
./.benchmarks
./.claude
./.concordia
./.dockerignore
./.editorconfig
./.github
./.gitignore
./.mypy_cache
./.pytest_cache
./.ruff_cache
./AUDIT.md
./CITATION.cff
./Dockerfile
./LICENSE
./Makefile
./README.md
./artifacts
./configs
./deploy
./dist
./docs
./experiments
./frontend
./pyproject.toml
./reports
./requirements-space.lock.txt
./requirements-space.txt
./scripts
./src
./tests
./uv.lock
configs/README.md
configs/baseline_nr_ahr.yaml
configs/scientist_local.yaml
configs/scientist_tools.yaml
configs/studies/hbb_promoter_annotations.yaml
configs/studies/hbb_promoter_evo2_protocol_v2.yaml
configs/studies/hbb_promoter_inputs.yaml
configs/studies/hbb_promoter_protocol.yaml
configs/virtual_cell/cellxgene_shh_e12_5.yaml
configs/virtual_cell/state_k562_release.yaml
configs/virtual_cell/state_source.yaml
deploy/hf-evo2-worker/README.md
deploy/hf-evo2-worker/app.py
deploy/hf-evo2-worker/qualification.py
deploy/hf-evo2-worker/requirements.txt
deploy/hf-evo2-worker/scoring.py
docs/ROADMAP.md
docs/adr/0001-local-single-scientist-stack.md
docs/adr/0002-molecular-experiment-dag.md
docs/adr/0003-public-api-shape.md
docs/adr/0004-concordia-product-depth.md
docs/adr/0005-campaign-postgres-persistence.md
docs/architecture.md
docs/backend-todo.md
docs/cellforge.md
docs/colonies.md
docs/deployment.md
docs/evo2-reading.md
docs/experiment-design.md
docs/frameworks.md
docs/guide.md
docs/img/antibody.png
docs/img/colony.png
docs/img/experiment.png
docs/img/investigation.png
docs/img/provenance.png
docs/img/stack.png
docs/local-runtime.md
docs/pitch.md
docs/reproducibility.md
docs/seed-scientist.md
docs/state-sandbox.md
docs/technical-overview.md
docs/tool-integration.md
docs/verification.md
docs/workspace.png
frontend/.concordia/events.sqlite3
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/playwright.config.ts
frontend/src/App.tsx
frontend/src/Graph.tsx
frontend/src/layout.worker.ts
frontend/src/main.tsx
frontend/src/style.css
frontend/src/types.ts
frontend/src/vite-env.d.ts
frontend/test-results/.last-run.json
frontend/tests/workspace.spec.ts
frontend/tsconfig.json
frontend/tsconfig.tsbuildinfo
frontend/vite.config.ts
scripts/__init__.py
scripts/antibody_dockq.py
scripts/benchmark_antibody_complexes.py
scripts/benchmark_structure_null.py
scripts/build_tsuboyama_summary.py
scripts/design_binder.py
scripts/paratope_counterfactual.py
scripts/render_sample_report.py
scripts/run_sample_e2e.py
scripts/score_complex_against_crystal.py
scripts/select_tsuboyama_domain.py
scripts/serve_local.py
scripts/ship_check.sh
scripts/structure_measurements.py
scripts/update_readme_benchmark.py
scripts/verify_benchmark.py
src/concordia/__init__.py
src/concordia/antibody/__init__.py
src/concordia/antibody/schema.py
src/concordia/api/__init__.py
src/concordia/api/app.py
src/concordia/api/workspace.py
src/concordia/artifacts.py
src/concordia/benchmarks/__init__.py
src/concordia/benchmarks/contracts.py
src/concordia/benchmarks/runner.py
src/concordia/campaigns/__init__.py
src/concordia/campaigns/artifacts.py
src/concordia/campaigns/assay.py
src/concordia/campaigns/benchmark.py
src/concordia/campaigns/connectors.py
src/concordia/campaigns/constraints.py
src/concordia/campaigns/design.py
src/concordia/campaigns/policy.py
src/concordia/campaigns/postgres.py
src/concordia/campaigns/recommendations.py
src/concordia/campaigns/redaction.py
src/concordia/campaigns/replay.py
src/concordia/campaigns/reporting.py
src/concordia/campaigns/schema.py
src/concordia/campaigns/security.py
src/concordia/campaigns/service.py
src/concordia/campaigns/study.py
src/concordia/campaigns/training.py
src/concordia/campaigns/validation.py
src/concordia/campaigns/worker.py
src/concordia/cellforge/__init__.py
src/concordia/cellforge/contracts.py
src/concordia/cellforge/local.py
src/concordia/cellforge/registry.py
src/concordia/cellforge/service.py
src/concordia/cli.py
src/concordia/colonies/__init__.py
src/concordia/colonies/demo.py
src/concordia/colonies/executor.py
src/concordia/colonies/live_run.py
src/concordia/colonies/qwen_demo.py
src/concordia/colonies/scheduler.py
src/concordia/colonies/schema.py
src/concordia/colonies/store.py
src/concordia/config.py
src/concordia/evaluation/.gitkeep
src/concordia/evaluation/__init__.py
src/concordia/evaluation/compare.py
src/concordia/evaluation/fitness.py
src/concordia/events/__init__.py
src/concordia/events/sqlite.py
src/concordia/evidence/.gitkeep
src/concordia/evidence/build.py
src/concordia/evidence/packets.py
src/concordia/evidence/schema.py
src/concordia/experiments/__init__.py
src/concordia/experiments/schema.py
src/concordia/experiments/service.py
src/concordia/explanations/.gitkeep
src/concordia/explanations/__init__.py
src/concordia/explanations/tree_shap.py
src/concordia/genomes/__init__.py
src/concordia/genomes/mutation.py
src/concordia/genomes/schema.py
src/concordia/genomics/__init__.py
src/concordia/genomics/boltz_gateway.py
src/concordia/genomics/boltz_nvidia.py
src/concordia/genomics/demo.py
src/concordia/genomics/evo2.py
src/concordia/genomics/evo2_attribution.py
src/concordia/genomics/evo2_forward_queue.py
src/concordia/genomics/evo2_generation_gateway.py
src/concordia/genomics/evo2_nvidia.py
src/concordia/genomics/evo2_protocol.py
src/concordia/genomics/evo2_real.py
src/concordia/genomics/evo2_zerogpu.py
src/concordia/genomics/ism.py
src/concordia/genomics/openfold2_nvidia.py
src/concordia/genomics/postgres_backend.py
src/concordia/genomics/proteinmpnn_nvidia.py
src/concordia/genomics/rate_limiting.py
src/concordia/genomics/rfdiffusion_nvidia.py
src/concordia/genomics/schema.py
src/concordia/genomics/structure_gateway.py
src/concordia/graph/__init__.py
src/concordia/graph/schema.py
src/concordia/ingestion/__init__.py
src/concordia/ingestion/index.py
src/concordia/ingestion/parsers.py
src/concordia/ingestion/schema.py
src/concordia/ingestion/service.py
src/concordia/interventions/.gitkeep
src/concordia/interventions/transform.py
src/concordia/predictors/__init__.py
src/concordia/predictors/baseline.py
src/concordia/predictors/data.py
src/concordia/predictors/fingerprints.py
src/concordia/predictors/split.py
src/concordia/reporting/.gitkeep
src/concordia/reporting/__init__.py
src/concordia/reporting/demo.py
src/concordia/reporting/workspace.py
src/concordia/runtime/__init__.py
src/concordia/runtime/contracts.py
src/concordia/runtime/service.py
src/concordia/runtime/state_machine.py
src/concordia/runtime/worker.py
src/concordia/scheduling/__init__.py
src/concordia/scheduling/jobs.py
src/concordia/scientific/__init__.py
src/concordia/scientific/extensions.py
src/concordia/scientific/frameworks.py
src/concordia/scientific/protocol.py
src/concordia/scientist/.gitkeep
src/concordia/scientist/__init__.py
src/concordia/scientist/adapters.py
src/concordia/scientist/contracts.py
src/concordia/scientist/doctor.py
src/concordia/scientist/genomic_prompt.py
src/concordia/scientist/local_qualification.py
src/concordia/scientist/ollama.py
src/concordia/scientist/prompt.py
src/concordia/scientist/qualification.py
src/concordia/scientist/records.py
src/concordia/scientist/runtime.py
src/concordia/scientist/schema.py
src/concordia/scientist/session.py
src/concordia/scientist/tools.py
src/concordia/stability/__init__.py
src/concordia/stability/contracts.py
src/concordia/storage/__init__.py
src/concordia/storage/content.py
src/concordia/tools/__init__.py
src/concordia/tools/builtin.py
src/concordia/verification/__init__.py
src/concordia/verification/backtrack.py
src/concordia/verification/cross.py
src/concordia/verification/measurements.py
src/concordia/verification/structure_baseline.py
src/concordia/verification/structure_rules.py
src/concordia/virtual_cell/__init__.py
src/concordia/virtual_cell/cellxgene.py
src/concordia/virtual_cell/contracts.py
src/concordia/virtual_cell/demo.py
src/concordia/virtual_cell/sandbox.py
src/concordia/virtual_cell/state_release.py
src/concordia/virtual_cell/state_source.py
tests/integration/.gitkeep
tests/integration/test_campaign_api.py
tests/integration/test_experiment_sandbox.py
tests/integration/test_public_api_security.py
tests/integration/test_run_api.py
tests/integration/test_workspace.py
tests/integration/test_workspace_interactive_evo2.py
tests/unit/.gitkeep
tests/unit/test_antibody.py
tests/unit/test_benchmarks.py
tests/unit/test_binder_design_nvidia.py
tests/unit/test_boltz_gateway.py
tests/unit/test_boltz_nvidia.py
tests/unit/test_campaigns.py
tests/unit/test_cellforge.py
tests/unit/test_cellxgene_ingestion.py
tests/unit/test_colonies.py
tests/unit/test_colony_live_run.py
tests/unit/test_config.py
tests/unit/test_cross_verification.py
tests/unit/test_data.py
tests/unit/test_deployment_security.py
tests/unit/test_evaluation.py
tests/unit/test_evo2_attribution.py
tests/unit/test_evo2_forward_queue.py
tests/unit/test_evo2_generation_gateway.py
tests/unit/test_evo2_protocol.py
tests/unit/test_evo2_worker_qualification.py
tests/unit/test_evo2_worker_scoring_parity.py
tests/unit/test_evo2_zerogpu.py
tests/unit/test_experiments.py
tests/unit/test_fingerprints.py
tests/unit/test_genomes.py
tests/unit/test_genomic_graph.py
tests/unit/test_hosted_scientist.py
tests/unit/test_ingestion.py
tests/unit/test_nvidia_evo2.py
tests/unit/test_openfold2_nvidia.py
tests/unit/test_packets.py
tests/unit/test_postgres_backend.py
tests/unit/test_protocol_gate.py
tests/unit/test_runtime.py
tests/unit/test_scientific_extensions.py
tests/unit/test_scientist_records.py
tests/unit/test_scientist_session.py
tests/unit/test_scientist_tools.py
tests/unit/test_scripts_import.py
tests/unit/test_seed_scientist.py
tests/unit/test_split.py
tests/unit/test_sqlite_rate_limiter.py
tests/unit/test_stability_contracts.py
tests/unit/test_state_release.py
tests/unit/test_state_source.py
tests/unit/test_structure_baseline_script.py
tests/unit/test_structure_gateway.py
tests/unit/test_structure_rules.py
tests/unit/test_study_manifest.py
tests/unit/test_virtual_cell.py
tests/unit/test_virtual_cell_configs.py
tests/unit/test_workers.py

## Appendix B — verbatim verification output

### Ruff

E401 [*] Multiple imports on one line
 --> scripts/score_complex_against_crystal.py:1:1
  |
1 | import json, itertools, numpy as np
  | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2 | from Bio.PDB import MMCIFParser
3 | from Bio import Align
  |
help: Split imports
  |
  - import json, itertools, numpy as np
1 + import json
2 + import itertools
3 + import numpy as np
4 | from Bio.PDB import MMCIFParser
  |

I001 [*] Import block is un-sorted or un-formatted
 --> scripts/score_complex_against_crystal.py:1:1
  |
1 | / import json, itertools, numpy as np
2 | | from Bio.PDB import MMCIFParser
3 | | from Bio import Align
4 | | from Bio.PDB.Polypeptide import three_to_index, index_to_one
  | |____________________________________________________________^
5 |   p=MMCIFParser(QUIET=True)
6 |   pred=p.get_structure("p","pred.cif")[0]; xt=p.get_structure("x","crystal.cif")[0]
  |
help: Organize imports
  |
  - import json, itertools, numpy as np
1 + import itertools
2 + import json
3 +
4 + import numpy as np
5 + from Bio import Align
6 | from Bio.PDB import MMCIFParser
  - from Bio import Align
  - from Bio.PDB.Polypeptide import three_to_index, index_to_one
7 + from Bio.PDB.Polypeptide import index_to_one, three_to_index
8 +
9 | p=MMCIFParser(QUIET=True)
  |

F401 [*] `itertools` imported but unused
 --> scripts/score_complex_against_crystal.py:1:14
  |
1 | import json, itertools, numpy as np
  |              ^^^^^^^^^
2 | from Bio.PDB import MMCIFParser
3 | from Bio import Align
  |
help: Remove unused import: `itertools`
  |
  - import json, itertools, numpy as np
1 + import json, numpy as np
2 | from Bio.PDB import MMCIFParser
  |

E702 Multiple statements on one line (semicolon)
 --> scripts/score_complex_against_crystal.py:6:40
  |
4 | from Bio.PDB.Polypeptide import three_to_index, index_to_one
5 | p=MMCIFParser(QUIET=True)
6 | pred=p.get_structure("p","pred.cif")[0]; xt=p.get_structure("x","crystal.cif")[0]
  |                                        ^
7 | def chains(m): return {c.id:[r for r in c if r.id[0]==" " and "CA" in r] for c in m}
8 | _cp,cx=chains(pred),chains(xt); cp={"H":_cp["A"],"L":_cp["B"],"Y":_cp["C"]}
  |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:8:31
   |
 6 | pred=p.get_structure("p","pred.cif")[0]; xt=p.get_structure("x","crystal.cif")[0]
 7 | def chains(m): return {c.id:[r for r in c if r.id[0]==" " and "CA" in r] for c in m}
 8 | _cp,cx=chains(pred),chains(xt); cp={"H":_cp["A"],"L":_cp["B"],"Y":_cp["C"]}
   |                               ^
 9 | print("pred chains:",{k:len(v) for k,v in cp.items()}); print("xtal chains:",{k:len(v) for k,v in cx.items()})
10 | def seq(rs):
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:9:55
   |
 7 | def chains(m): return {c.id:[r for r in c if r.id[0]==" " and "CA" in r] for c in m}
 8 | _cp,cx=chains(pred),chains(xt); cp={"H":_cp["A"],"L":_cp["B"],"Y":_cp["C"]}
 9 | print("pred chains:",{k:len(v) for k,v in cp.items()}); print("xtal chains:",{k:len(v) for k,v in cx.items()})
   |                                                       ^
10 | def seq(rs):
11 |     out=""
   |

E501 Line too long (110 > 100)
  --> scripts/score_complex_against_crystal.py:9:101
   |
 7 | def chains(m): return {c.id:[r for r in c if r.id[0]==" " and "CA" in r] for c in m}
 8 | _cp,cx=chains(pred),chains(xt); cp={"H":_cp["A"],"L":_cp["B"],"Y":_cp["C"]}
 9 | print("pred chains:",{k:len(v) for k,v in cp.items()}); print("xtal chains:",{k:len(v) for k,v in cx.items()})
   |                                                                                                     ^^^^^^^^^^
10 | def seq(rs):
11 |     out=""
   |

E701 Multiple statements on one line (colon)
  --> scripts/score_complex_against_crystal.py:13:12
   |
11 |     out=""
12 |     for r in rs:
13 |         try: out+=index_to_one(three_to_index(r.get_resname()))
   |            ^
14 |         except Exception: out+="X"
15 |     return out
   |

E701 Multiple statements on one line (colon)
  --> scripts/score_complex_against_crystal.py:14:25
   |
12 |     for r in rs:
13 |         try: out+=index_to_one(three_to_index(r.get_resname()))
14 |         except Exception: out+="X"
   |                         ^
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:16:27
   |
14 |         except Exception: out+="X"
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |                           ^
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:16:45
   |
14 |         except Exception: out+="X"
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |                                             ^
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:16:63
   |
14 |         except Exception: out+="X"
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |                                                               ^
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:16:85
   |
14 |         except Exception: out+="X"
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |                                                                                     ^
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |

E501 Line too long (132 > 100)
  --> scripts/score_complex_against_crystal.py:16:101
   |
14 |         except Exception: out+="X"
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |                                                                                                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:16:107
   |
14 |         except Exception: out+="X"
15 |     return out
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
   |                                                                                                           ^
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:18:35
   |
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |                                   ^
19 |     for (s1,e1),(s2,e2) in zip(*aln.aligned):
20 |         for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:18:42
   |
16 | al=Align.PairwiseAligner(); al.mode="global"; al.match_score=2; al.mismatch_score=-1; al.open_gap_score=-3; al.extend_gap_score=-0.5
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
   |                                          ^
19 |     for (s1,e1),(s2,e2) in zip(*aln.aligned):
20 |         for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
   |

B905 `zip()` without an explicit `strict=` parameter
  --> scripts/score_complex_against_crystal.py:19:28
   |
17 | def matched(a,b):
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
19 |     for (s1,e1),(s2,e2) in zip(*aln.aligned):
   |                            ^^^^^^^^^^^^^^^^^
20 |         for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
21 |     return pa,pb
   |
help: Add explicit value for parameter `strict=`

B905 `zip()` without an explicit `strict=` parameter
  --> scripts/score_complex_against_crystal.py:20:20
   |
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
19 |     for (s1,e1),(s2,e2) in zip(*aln.aligned):
20 |         for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
   |                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
21 |     return pa,pb
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
   |
help: Add explicit value for parameter `strict=`

E701 Multiple statements on one line (colon)
  --> scripts/score_complex_against_crystal.py:20:50
   |
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
19 |     for (s1,e1),(s2,e2) in zip(*aln.aligned):
20 |         for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
   |                                                  ^
21 |     return pa,pb
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:20:67
   |
18 |     aln=al.align(seq(a),seq(b))[0]; pa=[];pb=[]
19 |     for (s1,e1),(s2,e2) in zip(*aln.aligned):
20 |         for i,j in zip(range(s1,e1),range(s2,e2)): pa.append(a[i]);pb.append(b[j])
   |                                                                   ^
21 |     return pa,pb
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:24:30
   |
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
23 | def kabsch(P,Q):
24 |     pc,qc=P.mean(0),Q.mean(0); H=(P-pc).T@(Q-qc); U,S,Vt=np.linalg.svd(H); d=np.sign(np.linalg.det(Vt.T@U.T))
   |                              ^
25 |     R=Vt.T@np.diag([1,1,d])@U.T; return R,pc,qc
26 | def rmsd(P,Q): return float(np.sqrt(((P-Q)**2).sum(1).mean()))
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:24:49
   |
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
23 | def kabsch(P,Q):
24 |     pc,qc=P.mean(0),Q.mean(0); H=(P-pc).T@(Q-qc); U,S,Vt=np.linalg.svd(H); d=np.sign(np.linalg.det(Vt.T@U.T))
   |                                                 ^
25 |     R=Vt.T@np.diag([1,1,d])@U.T; return R,pc,qc
26 | def rmsd(P,Q): return float(np.sqrt(((P-Q)**2).sum(1).mean()))
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:24:74
   |
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
23 | def kabsch(P,Q):
24 |     pc,qc=P.mean(0),Q.mean(0); H=(P-pc).T@(Q-qc); U,S,Vt=np.linalg.svd(H); d=np.sign(np.linalg.det(Vt.T@U.T))
   |                                                                          ^
25 |     R=Vt.T@np.diag([1,1,d])@U.T; return R,pc,qc
26 | def rmsd(P,Q): return float(np.sqrt(((P-Q)**2).sum(1).mean()))
   |

E501 Line too long (109 > 100)
  --> scripts/score_complex_against_crystal.py:24:101
   |
22 | def xyz(rs): return np.array([r["CA"].coord for r in rs])
23 | def kabsch(P,Q):
24 |     pc,qc=P.mean(0),Q.mean(0); H=(P-pc).T@(Q-qc); U,S,Vt=np.linalg.svd(H); d=np.sign(np.linalg.det(Vt.T@U.T))
   |                                                                                                     ^^^^^^^^^
25 |     R=Vt.T@np.diag([1,1,d])@U.T; return R,pc,qc
26 | def rmsd(P,Q): return float(np.sqrt(((P-Q)**2).sum(1).mean()))
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:25:32
   |
23 | def kabsch(P,Q):
24 |     pc,qc=P.mean(0),Q.mean(0); H=(P-pc).T@(Q-qc); U,S,Vt=np.linalg.svd(H); d=np.sign(np.linalg.det(Vt.T@U.T))
25 |     R=Vt.T@np.diag([1,1,d])@U.T; return R,pc,qc
   |                                ^
26 | def rmsd(P,Q): return float(np.sqrt(((P-Q)**2).sum(1).mean()))
27 | pairs={k:matched(cp[k],cx[k]) for k in ("H","L","Y")}
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:31:22
   |
29 | res={}
30 | for k,(a,b) in pairs.items():
31 |     P,Q=xyz(a),xyz(b); R,pc,qc=kabsch(P,Q); res[f"{k}_rmsd_CA"]=round(rmsd((P-pc)@R.T+qc,Q),2)
   |                      ^
32 | # antibody frame (H+L), then antigen RMSD in that frame (docking quality)
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:31:43
   |
29 | res={}
30 | for k,(a,b) in pairs.items():
31 |     P,Q=xyz(a),xyz(b); R,pc,qc=kabsch(P,Q); res[f"{k}_rmsd_CA"]=round(rmsd((P-pc)@R.T+qc,Q),2)
   |                                           ^
32 | # antibody frame (H+L), then antigen RMSD in that frame (docking quality)
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:33:55
   |
31 |     P,Q=xyz(a),xyz(b); R,pc,qc=kabsch(P,Q); res[f"{k}_rmsd_CA"]=round(rmsd((P-pc)@R.T+qc,Q),2)
32 | # antibody frame (H+L), then antigen RMSD in that frame (docking quality)
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
   |                                                       ^
34 | R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
35 | Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
   |

E501 Line too long (110 > 100)
  --> scripts/score_complex_against_crystal.py:33:101
   |
31 |     P,Q=xyz(a),xyz(b); R,pc,qc=kabsch(P,Q); res[f"{k}_rmsd_CA"]=round(rmsd((P-pc)@R.T+qc,Q),2)
32 | # antibody frame (H+L), then antigen RMSD in that frame (docking quality)
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
   |                                                                                                     ^^^^^^^^^^
34 | R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
35 | Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:34:24
   |
32 | # antibody frame (H+L), then antigen RMSD in that frame (docking quality)
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
34 | R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
   |                        ^
35 | Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
36 | # interface contacts (CA-CA < 8A between antibody and antigen) crystal vs predicted, residue-aligned
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:35:35
   |
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
34 | R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
35 | Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
   |                                   ^
36 | # interface contacts (CA-CA < 8A between antibody and antigen) crystal vs predicted, residue-aligned
37 | def contacts(chain_pairs, which):
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:35:59
   |
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
34 | R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
35 | Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
   |                                                           ^
36 | # interface contacts (CA-CA < 8A between antibody and antigen) crystal vs predicted, residue-aligned
37 | def contacts(chain_pairs, which):
   |

E501 Line too long (123 > 100)
  --> scripts/score_complex_against_crystal.py:35:101
   |
33 | Pab=np.vstack([xyz(pairs["H"][0]),xyz(pairs["L"][0])]); Qab=np.vstack([xyz(pairs["H"][1]),xyz(pairs["L"][1])])
34 | R,pc,qc=kabsch(Pab,Qab); res["antibody_HL_rmsd_CA"]=round(rmsd((Pab-pc)@R.T+qc,Qab),2)
35 | Pag=(xyz(pairs["Y"][0])-pc)@R.T+qc; Qag=xyz(pairs["Y"][1]); res["antigen_rmsd_in_antibody_frame_CA"]=round(rmsd(Pag,Qag),2)
   |                                                                                                     ^^^^^^^^^^^^^^^^^^^^^^^
36 | # interface contacts (CA-CA < 8A between antibody and antigen) crystal vs predicted, residue-aligned
37 | def contacts(chain_pairs, which):
   |

E701 Multiple statements on one line (colon)
  --> scripts/score_complex_against_crystal.py:44:76
   |
42 |         a=chain_pairs[k][which][i]["CA"].coord
43 |         for (_,j) in ag:
44 |             if np.linalg.norm(a-chain_pairs["Y"][which][j]["CA"].coord)<8.0: out.add((k,chain_pairs[k][which][i].id[1] if which==1 els…
   |                                                                            ^
45 |     return out
46 | def cset(which):
   |

E501 Line too long (144 > 100)
  --> scripts/score_complex_against_crystal.py:44:101
   |
42 | …
43 | …
44 | …j]["CA"].coord)<8.0: out.add((k,chain_pairs[k][which][i].id[1] if which==1 else None,j))
   |                                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
45 | …
46 | …
   |

E701 Multiple statements on one line (colon)
  --> scripts/score_complex_against_crystal.py:51:69
   |
49 |         for i,ra in enumerate(pairs[k][which]):
50 |             for j,rb in enumerate(pairs["Y"][which]):
51 |                 if np.linalg.norm(ra["CA"].coord-rb["CA"].coord)<8.0: s.add((k,i,j))
   |                                                                     ^
52 |     return s
53 | cx_set,cp_set=cset(1),cset(0)
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:54:22
   |
52 |     return s
53 | cx_set,cp_set=cset(1),cset(0)
54 | tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
   |                      ^
55 | res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
56 | print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:54:66
   |
52 |     return s
53 | cx_set,cp_set=cset(1),cset(0)
54 | tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
   |                                                                  ^
55 | res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
56 | print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
   |

E501 Line too long (106 > 100)
  --> scripts/score_complex_against_crystal.py:54:101
   |
52 |     return s
53 | cx_set,cp_set=cset(1),cset(0)
54 | tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
   |                                                                                                     ^^^^^^
55 | res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
56 | print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:55:58
   |
53 | cx_set,cp_set=cset(1),cset(0)
54 | tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
55 | res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
   |                                                          ^
56 | print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
   |

E501 Line too long (113 > 100)
  --> scripts/score_complex_against_crystal.py:55:101
   |
53 | cx_set,cp_set=cset(1),cset(0)
54 | tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
55 | res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
   |                                                                                                     ^^^^^^^^^^^^^
56 | print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
   |

E702 Multiple statements on one line (semicolon)
  --> scripts/score_complex_against_crystal.py:56:32
   |
54 | tp=len(cx_set&cp_set); res["interface_pairs_crystal"]=len(cx_set); res["interface_pairs_pred"]=len(cp_set)
55 | res["interface_precision"]=round(tp/max(1,len(cp_set)),3); res["interface_recall"]=round(tp/max(1,len(cx_set)),3)
56 | print(json.dumps(res,indent=1)); json.dump(res,open("3hfm_scores.json","w"))
   |                                ^

I001 [*] Import block is un-sorted or un-formatted
   --> src/concordia/api/workspace.py:3:1
    |
  1 |   """Read-only demonstration API and static scientific workspace host."""
  2 |
  3 | / from __future__ import annotations
  4 | |
  5 | | import asyncio
  6 | | import hashlib
  7 | | import json
  8 | | import logging
  9 | | import os
 10 | | import threading
 11 | | import uuid
 12 | | from collections.abc import Awaitable, Callable
 13 | | from copy import deepcopy
 14 | | from dataclasses import asdict
 15 | | from datetime import UTC, datetime
 16 | | from pathlib import Path
 17 | | from typing import Literal, cast
 18 | |
 19 | | from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
 20 | | from fastapi.responses import JSONResponse, Response, StreamingResponse
 21 | | from fastapi.staticfiles import StaticFiles
 22 | | from pydantic import BaseModel, ConfigDict, Field
 23 | |
 24 | | from concordia.campaigns.artifacts import CampaignArtifactStore
 25 | | from concordia.campaigns.assay import parse_assay_csv
 26 | | from concordia.campaigns.benchmark import benchmark_digest, run_retrospective_benchmark
 27 | | from concordia.campaigns.constraints import candidate_constraint_report
 28 | | from concordia.campaigns.connectors import (
 29 | |     BioNeMoInferenceConnector,
 30 | |     BioNeMoInferenceRunner,
 31 | |     BioNeMoTrainingConnector,
 32 | |     BioNeMoTrainingRunner,
 33 | |     BoltzCampaignConnector,
 34 | |     HttpBioNeMoInferenceRunner,
 35 | |     HttpBioNeMoTrainingRunner,
 36 | |     ProteinBaselineTrainingConnector,
 37 | |     ProteinMPNNCampaignConnector,
 38 | |     RFdiffusionCampaignConnector,
 39 | | )
 40 | | from concordia.campaigns.design import CampaignDesignRecord, build_binder_design_plan
 41 | | from concordia.campaigns.postgres import PostgresCampaignStore
 42 | | from concordia.campaigns.recommendations import SelectionCandidate, select_candidates
 43 | | from concordia.campaigns.replay import replay_execute, replay_read
 44 | | from concordia.campaigns.reporting import build_report_manifest, verify_report_manifest
 45 | | from concordia.campaigns.schema import (
 46 | |     Campaign,
 47 | |     CampaignAuditEvent,
 48 | |     CampaignModelJob,
 49 | |     CampaignModelRun,
 50 | |     CampaignRound,
 51 | |     Candidate,
 52 | |     DatasetSnapshot,
 53 | |     EvidenceClaim,
 54 | |     Measurement,
 55 | |     Recommendation,
 56 | | )
 57 | | from concordia.campaigns.security import CampaignAction, CampaignPrincipal, require_action
 58 | | from concordia.campaigns.service import (
 59 | |     AddCandidateRequest,
 60 | |     CampaignConflictError,
 61 | |     CampaignNotFoundError,
 62 | |     CampaignStore,
 63 | |     CreateAccessGrantRequest,
 64 | |     CreateAccessGrantResponse,
 65 | |     CreateCampaignRequest,
 66 | |     CreateCampaignResponse,
 67 | |     CreateDesignPlanRequest,
 68 | |     CreateEvidenceClaimRequest,
 69 | |     CreateRoundRequest,
 70 | |     CreateStudyRequest,
 71 | |     EnqueueModelJobRequest,
 72 | |     ImportAssayCSVRequest,
 73 | |     RecordMeasurementRequest,
 74 | |     RecordModelRunRequest,
 75 | |     ReplayExecuteRequest,
 76 | |     TransitionCampaignRequest,
 77 | |     TransitionRoundRequest,
 78 | |     VerifyEvidenceClaimRequest,
 79 | | )
 80 | | from concordia.campaigns.study import CampaignStudy
 81 | | from concordia.campaigns.validation import (
 82 | |     ALLOWED_EXTERNAL_PROVIDERS,
 83 | |     ValidationCheck,
 84 | |     ValidationReport,
 85 | |     validate_campaign_round,
 86 | |     validate_recommendation_replay,
 87 | | )
 88 | | from concordia.campaigns.worker import CampaignModelWorker, ModelConnector, ModelConnectorError
 89 | | from concordia.colonies.live_run import run_live_colony
 90 | | from concordia.experiments.schema import (
 91 | |     CreateExperimentNodeRequest,
 92 | |     CreateExperimentRequest,
 93 | |     CreateExperimentResponse,
 94 | |     DnaPayload,
 95 | |     ExperimentComparison,
 96 | |     ExperimentManifest,
 97 | |     ExperimentNode,
 98 | |     ExperimentNodeKind,
 99 | |     ExperimentOperation,
100 | |     ModelRunPayload,
101 | |     StructurePayload,
102 | | )
103 | | from concordia.experiments.service import (
104 | |     ExperimentAccessError,
105 | |     ExperimentConflictError,
106 | |     ExperimentNodeNotFoundError,
107 | |     ExperimentNotFoundError,
108 | |     ExperimentStore,
109 | | )
110 | | from concordia.genomics.boltz_gateway import BoltzGateway
111 | | from concordia.genomics.boltz_nvidia import (
112 | |     BoltzComplexRequest,
113 | |     NvidiaHostedBoltzComplexResult,
114 | |     NvidiaHostedBoltzResult,
115 | |     NvidiaHostedBoltzRunner,
116 | | )
117 | | from concordia.genomics.evo2_attribution import ZeroGpuEvo2AttributionRunner
118 | | from concordia.genomics.evo2_forward_queue import Evo2ForwardJobQueue, JobNotFoundError
119 | | from concordia.genomics.evo2_generation_gateway import (
120 | |     Evo2GenerationGateway,
121 | |     RateLimitExceededError,
122 | | )
123 | | from concordia.genomics.evo2_nvidia import (
124 | |     NvidiaHostedEvo2GenerationRunner,
125 | |     NvidiaHostedGenerationResult,
126 | | )
127 | | from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
128 | | from concordia.genomics.evo2_real import RealEvo2Scorer
129 | | from concordia.genomics.evo2_zerogpu import ZeroGpuEvo2ForwardRunner
130 | | from concordia.genomics.openfold2_nvidia import (
131 | |     NvidiaHostedOpenFold2Result,
132 | |     NvidiaHostedOpenFold2Runner,
133 | | )
134 | | from concordia.genomics.proteinmpnn_nvidia import NvidiaHostedProteinMpnnRunner
135 | | from concordia.genomics.rate_limiting import SqliteRateLimiter
136 | | from concordia.genomics.rfdiffusion_nvidia import NvidiaHostedRFdiffusionRunner
137 | | from concordia.genomics.schema import GenomicSequence
138 | | from concordia.genomics.structure_gateway import StructureGateway
139 | | from concordia.reporting.workspace import build_workspace
140 | | from concordia.scientific.frameworks import framework_catalog
141 | | from concordia.verification.cross import StructureScope
142 | | from concordia.verification.structure_baseline import (
143 | |     StructureBaselineCase,
144 | |     run_structure_baseline,
145 | | )
146 | | from concordia.verification.structure_rules import (
147 | |     RULE_PACK_VERSION,
148 | |     StructureMeasurements,
149 | |     plausibility,
150 | |     verify_measurements,
151 | | )
    | |_^
152 |
153 |   HBB_CHECKPOINT = "arcinstitute/evo2_7b@bda0089f92582d5baabf0f22d9fc85f3588f6b58/evo2_7b.pt"
    |
help: Organize imports
   |
26 | from concordia.campaigns.benchmark import benchmark_digest, run_retrospective_benchmark
   - from concordia.campaigns.constraints import candidate_constraint_report
27 | from concordia.campaigns.connectors import (
--------------------------------------------------------------------------------
38 | )
39 + from concordia.campaigns.constraints import candidate_constraint_report
40 | from concordia.campaigns.design import CampaignDesignRecord, build_binder_design_plan
   |

E501 Line too long (101 > 100)
   --> src/concordia/api/workspace.py:768:101
    |
766 | …     },
767 | …     "bionemo_training": {
768 | …         "configured": bool(os.environ.get("CONCORDIA_BIONEMO_TRAINING_URL", "").strip()),
    |                                                                                           ^
769 | …         "status": "configured" if os.environ.get("CONCORDIA_BIONEMO_TRAINING_URL", "").strip() else "missing_private_endpoint",
770 | …         "last_success": "unknown",
    |

E501 Line too long (139 > 100)
   --> src/concordia/api/workspace.py:769:101
    |
767 | …
768 | …"CONCORDIA_BIONEMO_TRAINING_URL", "").strip()),
769 | …on.get("CONCORDIA_BIONEMO_TRAINING_URL", "").strip() else "missing_private_endpoint",
    |                                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
770 | …
771 | …
    |

E501 Line too long (102 > 100)
   --> src/concordia/api/workspace.py:773:101
    |
771 | …     },
772 | …     "bionemo_inference": {
773 | …         "configured": bool(os.environ.get("CONCORDIA_BIONEMO_INFERENCE_URL", "").strip()),
    |                                                                                           ^^
774 | …         "status": "configured" if os.environ.get("CONCORDIA_BIONEMO_INFERENCE_URL", "").strip() else "missing_private_endpoint",
775 | …         "last_success": "unknown",
    |

E501 Line too long (140 > 100)
   --> src/concordia/api/workspace.py:774:101
    |
772 | …
773 | …"CONCORDIA_BIONEMO_INFERENCE_URL", "").strip()),
774 | …on.get("CONCORDIA_BIONEMO_INFERENCE_URL", "").strip() else "missing_private_endpoint",
    |                                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
775 | …
776 | …
    |

E501 Line too long (107 > 100)
    --> src/concordia/api/workspace.py:1728:101
     |
1726 |             if round_record.campaign_id != campaign_id:
1727 |                 raise CampaignConflictError("round does not belong to campaign")
1728 |             return candidate_constraint_report(reference_sequence, candidate_sequence, protected_positions)
     |                                                                                                     ^^^^^^^
1729 |         except CampaignNotFoundError as error:
1730 |             raise HTTPException(status_code=404, detail="round not found") from error
     |

E501 Line too long (105 > 100)
  --> src/concordia/campaigns/constraints.py:34:101
   |
32 |         if actual_reference != expected:
33 |             violations.append(
34 |                 f"protected position {item.position} reference mismatch ({actual_reference}!={expected})"
   |                                                                                                     ^^^^^
35 |             )
36 |         elif actual_candidate != expected:
   |

E501 Line too long (101 > 100)
  --> src/concordia/campaigns/recommendations.py:64:101
   |
62 |         for candidate in candidates
63 |     ):
64 |         raise ValueError("insufficient evidence: candidate uncertainty exceeds the configured limit")
   |                                                                                                     ^
65 |     if policy == "random":
66 |         ordered = list(candidates)
   |

E501 Line too long (104 > 100)
  --> src/concordia/campaigns/recommendations.py:89:101
   |
87 |     if reference_candidate_id is not None:
88 |         reference = next(
89 |             (candidate for candidate in candidates if candidate.candidate_id == reference_candidate_id),
   |                                                                                                     ^^^^
90 |             None,
91 |         )
   |

E501 Line too long (110 > 100)
   --> src/concordia/campaigns/training.py:181:101
    |
179 | def predict_protein_baseline(result: ProteinBaselineResult, sequence: str) -> float:
180 |     """Predict one sequence while keeping the model explicitly non-scientific."""
181 |     return float(result.intercept + np.asarray(sequence_features(sequence)) @ np.asarray(result.coefficients))
    |                                                                                                     ^^^^^^^^^^

E501 Line too long (107 > 100)
   --> src/concordia/campaigns/training.py:192:101
    |
192 | def baseline_comparison(result: ProteinBaselineResult, dataset: FrozenProteinDataset) -> dict[str, object]:
    |                                                                                                     ^^^^^^^
193 |     """Return a transparent model-vs-constant comparison and uncertainty proxy."""
194 |     by_id = {example.candidate_id: example for example in dataset.examples}
    |

E501 Line too long (105 > 100)
   --> src/concordia/genomics/boltz_nvidia.py:262:101
    |
260 |                 "The MSA sent is a one-sequence self-reference, not a real multiple "
261 |                 "sequence alignment, which measurably reduces Boltz-2 accuracy.",
262 |                 "Per-residue confidence is reported as a model diagnostic, not experimental validation.",
    |                                                                                                     ^^^^^
263 |                 "The input protein is not biologically verified to be encoded by any "
264 |                 "real organism's genome.",
    |

Found 55 errors.
[*] 4 fixable with the `--fix` option (2 hidden fixes can be enabled with the `--unsafe-fixes` option).

### Mypy project config

tests/unit/test_evo2_worker_qualification.py:89: error: Module has no attribute "EXPECTED_FILES"  [attr-defined]
scripts/structure_measurements.py:53: error: Function is missing a return type annotation  [no-untyped-def]
scripts/structure_measurements.py:57: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/structure_measurements.py:82: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/verify_benchmark.py:49: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/verify_benchmark.py:53: error: Argument "kind" to "ProvenanceArtifact" has incompatible type "str"; expected "Literal['sequence', 'model', 'annotation', 'literature', 'evidence', 'claim']"  [arg-type]
scripts/benchmark_structure_null.py:77: error: Value of type "object" is not indexable  [index]
tests/unit/test_cellforge.py:391: error: Argument "arguments" to "request" has incompatible type "dict[str, str]"; expected "dict[str, object] | None"  [arg-type]
tests/unit/test_cellforge.py:391: note: "dict" is invariant -- see https://mypy.readthedocs.io/en/stable/common_issues.html#variance
tests/unit/test_cellforge.py:391: note: Consider using "Mapping" instead, which is covariant in the value type
tests/unit/test_cellforge.py:450: error: Argument "arguments" to "request" has incompatible type "dict[str, str]"; expected "dict[str, object] | None"  [arg-type]
tests/unit/test_cellforge.py:450: note: "dict" is invariant -- see https://mypy.readthedocs.io/en/stable/common_issues.html#variance
tests/unit/test_cellforge.py:450: note: Consider using "Mapping" instead, which is covariant in the value type
tests/unit/test_cellforge.py:452: error: Argument "arguments" to "request" has incompatible type "dict[str, str]"; expected "dict[str, object] | None"  [arg-type]
tests/unit/test_cellforge.py:452: note: "dict" is invariant -- see https://mypy.readthedocs.io/en/stable/common_issues.html#variance
tests/unit/test_cellforge.py:452: note: Consider using "Mapping" instead, which is covariant in the value type
tests/integration/test_run_api.py:30: error: "Callable[[MutableMapping[str, Any], Callable[[], Awaitable[MutableMapping[str, Any]]], Callable[[MutableMapping[str, Any]], Awaitable[None]]], Awaitable[None]]" has no attribute "state"  [attr-defined]
scripts/design_binder.py:104: error: Argument "polymers" to "BoltzComplexRequest" has incompatible type "tuple[dict[str, str], dict[str, str]]"; expected "tuple[BoltzPolymer, ...]"  [arg-type]
tests/unit/test_genomic_graph.py:29: error: Argument "node_type" to "GraphNode" has incompatible type "str"; expected "GraphNodeType"  [arg-type]
tests/unit/test_genomic_graph.py:32: error: Argument "node_type" to "GraphNode" has incompatible type "str"; expected "GraphNodeType"  [arg-type]
tests/unit/test_genomic_graph.py:39: error: Argument "relation" to "GraphEdge" has incompatible type "str"; expected "GraphRelation"  [arg-type]
tests/unit/test_packets.py:33: error: Item "None" of "ExplanationEvidence | None" has no attribute "top_positive"  [union-attr]
tests/unit/test_state_release.py:81: error: Argument "selected_on" to "StateReleaseSelection" has incompatible type "str"; expected "date"  [arg-type]
tests/unit/test_state_release.py:82: error: Argument "accepted_on" to "StateTermsAcceptance" has incompatible type "str"; expected "date"  [arg-type]
scripts/score_complex_against_crystal.py:7: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:10: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:17: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:22: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:23: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:26: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:37: error: Function is missing a type annotation  [no-untyped-def]
scripts/score_complex_against_crystal.py:46: error: Function is missing a type annotation  [no-untyped-def]
scripts/benchmark_antibody_complexes.py:88: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/benchmark_antibody_complexes.py:94: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/benchmark_antibody_complexes.py:112: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/benchmark_antibody_complexes.py:122: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
scripts/benchmark_antibody_complexes.py:126: error: Function is missing a return type annotation  [no-untyped-def]
scripts/run_sample_e2e.py:64: error: Function is missing a return type annotation  [no-untyped-def]
scripts/run_sample_e2e.py:64: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
tests/unit/test_antibody.py:11: error: Argument "chains" to "AntibodyDesignRequest" has incompatible type "tuple[dict[str, str], dict[str, str]]"; expected "tuple[AntibodyChain, ...]"  [arg-type]
tests/unit/test_antibody.py:46: error: Argument "chains" to "AntibodyDesignRequest" has incompatible type "tuple[dict[str, str]]"; expected "tuple[AntibodyChain, ...]"  [arg-type]
tests/unit/test_boltz_nvidia.py:124: error: Argument "polymers" to "BoltzComplexRequest" has incompatible type "tuple[dict[str, str], dict[str, str], dict[str, str]]"; expected "tuple[BoltzPolymer, ...]"  [arg-type]
tests/unit/test_boltz_nvidia.py:161: error: Argument "polymers" to "BoltzComplexRequest" has incompatible type "tuple[dict[str, str], dict[str, str]]"; expected "tuple[BoltzPolymer, ...]"  [arg-type]
tests/unit/test_boltz_nvidia.py:183: error: Argument "polymers" to "BoltzComplexRequest" has incompatible type "tuple[dict[str, str], dict[str, str]]"; expected "tuple[BoltzPolymer, ...]"  [arg-type]
tests/unit/test_evo2_generation_gateway.py:49: error: Argument 1 to "Evo2GenerationGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedEvo2GenerationRunner"  [arg-type]
tests/unit/test_evo2_generation_gateway.py:63: error: Argument 1 to "Evo2GenerationGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedEvo2GenerationRunner"  [arg-type]
tests/unit/test_evo2_generation_gateway.py:81: error: Argument 1 to "Evo2GenerationGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedEvo2GenerationRunner"  [arg-type]
tests/unit/test_evo2_generation_gateway.py:98: error: Argument 1 to "Evo2GenerationGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedEvo2GenerationRunner"  [arg-type]
tests/unit/test_evo2_generation_gateway.py:115: error: Argument 1 to "Evo2GenerationGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedEvo2GenerationRunner"  [arg-type]
tests/unit/test_boltz_gateway.py:40: error: Argument 1 to "BoltzGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedBoltzRunner"  [arg-type]
tests/unit/test_boltz_gateway.py:52: error: Argument 1 to "BoltzGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedBoltzRunner"  [arg-type]
tests/unit/test_boltz_gateway.py:65: error: Argument 1 to "BoltzGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedBoltzRunner"  [arg-type]
tests/unit/test_boltz_gateway.py:83: error: Argument 1 to "BoltzGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedBoltzRunner"  [arg-type]
tests/unit/test_boltz_gateway.py:85: error: Argument "polymers" to "BoltzComplexRequest" has incompatible type "tuple[dict[str, str], dict[str, str]]"; expected "tuple[BoltzPolymer, ...]"  [arg-type]
tests/unit/test_boltz_gateway.py:100: error: Argument 1 to "BoltzGateway" has incompatible type "FakeRunner"; expected "NvidiaHostedBoltzRunner"  [arg-type]
tests/unit/test_boltz_gateway.py:104: error: Argument "polymers" to "BoltzComplexRequest" has incompatible type "tuple[dict[str, Collection[str]], dict[str, str]]"; expected "tuple[BoltzPolymer, ...]"  [arg-type]
tests/unit/test_seed_scientist.py:204: error: Argument 1 to "get_bytes" of "ContentAddressedStore" has incompatible type "str | None"; expected "str"  [arg-type]
tests/unit/test_seed_scientist.py:328: error: Unsupported right operand type for in ("str | None")  [operator]
tests/unit/test_stability_contracts.py:95: error: "object" has no attribute "__iter__"; maybe "__dir__" or "__str__"? (not iterable)  [attr-defined]
tests/unit/test_evo2_zerogpu.py:21: error: Argument "target" to "Evo2ScoringSemantics" has incompatible type "str"; expected "Literal['mean_next_base_log_likelihood']"  [arg-type]
tests/unit/test_evo2_zerogpu.py:86: error: Argument 1 to "get_bytes" of "ContentAddressedStore" has incompatible type "str | None"; expected "str"  [arg-type]
tests/unit/test_evo2_zerogpu.py:87: error: Argument 1 to "get_bytes" of "ContentAddressedStore" has incompatible type "str | None"; expected "str"  [arg-type]
tests/unit/test_evo2_zerogpu.py:89: error: Argument 1 to "get_bytes" of "ContentAddressedStore" has incompatible type "str | None"; expected "str"  [arg-type]
tests/unit/test_evo2_attribution.py:26: error: Argument "target" to "Evo2ScoringSemantics" has incompatible type "str"; expected "Literal['mean_next_base_log_likelihood']"  [arg-type]
tests/unit/test_evo2_attribution.py:96: error: Argument 5 to "ZeroGpuEvo2AttributionRunner" has incompatible type "**dict[str, object]"; expected "int"  [arg-type]
tests/unit/test_evo2_attribution.py:96: error: Argument 5 to "ZeroGpuEvo2AttributionRunner" has incompatible type "**dict[str, object]"; expected "float"  [arg-type]
tests/unit/test_evo2_attribution.py:96: error: Argument 5 to "ZeroGpuEvo2AttributionRunner" has incompatible type "**dict[str, object]"; expected "str | None"  [arg-type]
tests/unit/test_campaigns.py:563: error: Argument "status" to "Measurement" has incompatible type "str"; expected "AssayStatus"  [arg-type]
tests/unit/test_campaigns.py:991: error: Argument 1 to "BoltzCampaignConnector" has incompatible type "_FakeBoltzGateway"; expected "BoltzGateway"  [arg-type]
tests/unit/test_campaigns.py:1067: error: Argument "client" to "HttpBioNeMoTrainingRunner" has incompatible type "test_campaigns.Client@1058"; expected "httpx._client.Client | None"  [arg-type]
tests/unit/test_campaigns.py:1102: error: Argument "client" to "HttpBioNeMoTrainingRunner" has incompatible type "test_campaigns.Client@1092"; expected "httpx._client.Client | None"  [arg-type]
tests/unit/test_campaigns.py:1135: error: Argument "client" to "HttpBioNeMoInferenceRunner" has incompatible type "test_campaigns.Client@1125"; expected "httpx._client.Client | None"  [arg-type]
tests/unit/test_campaigns.py:1205: error: Argument "client" to "HttpBioNeMoInferenceRunner" has incompatible type "test_campaigns.Client@1196"; expected "httpx._client.Client | None"  [arg-type]
Found 67 errors in 22 files (checked 217 source files)

### Mypy strict src

src/concordia/campaigns/recommendations.py:80: error: Unused "type: ignore" comment  [unused-ignore]
src/concordia/evidence/schema.py:96: error: Returning Any from function declared to return "dict[str, object]"  [no-any-return]
src/concordia/campaigns/service.py:1071: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/predictors/data.py:50: error: Call to untyped function "MurckoScaffoldSmiles" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:256: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/campaigns/postgres.py:267: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:290: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:322: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:341: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:355: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:392: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:418: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:431: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:446: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:477: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:493: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:507: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:561: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:577: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:589: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:601: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:628: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:712: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:732: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:745: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:787: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:798: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:832: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:856: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:867: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:882: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:924: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:950: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:966: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:976: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/campaigns/postgres.py:980: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1020: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1061: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1107: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1131: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1155: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1167: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1180: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1192: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1213: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1225: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1283: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1292: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1314: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1355: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1372: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1397: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1417: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1450: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1467: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1477: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/campaigns/postgres.py:1511: error: Call to untyped function "_connect" in typed context  [no-untyped-call]
src/concordia/scientist/tools.py:147: error: Call to untyped function "HeavyAtomCount" in typed context  [no-untyped-call]
src/concordia/api/app.py:44: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/campaigns/connectors.py:278: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:787: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:791: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:795: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:890: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:898: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:913: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:932: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:958: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:967: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:975: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:982: error: Call to untyped function "source" in typed context  [no-untyped-call]
src/concordia/api/workspace.py:989: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:2615: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:2619: error: Function is missing a return type annotation  [no-untyped-def]
src/concordia/api/workspace.py:2626: error: Function is missing a return type annotation  [no-untyped-def]
Found 75 errors in 9 files (checked 141 source files)

### Pytest

........................................................................ [ 19%]
........................................................................ [ 38%]
........................................................................ [ 57%]
........................................................................ [ 77%]
........................................................................ [ 96%]
.............                                                            [100%]
=============================== warnings summary ===============================
.venv/lib/python3.13/site-packages/fastapi/testclient.py:1
  /Users/srikarjy/resume_projects/concordia/.venv/lib/python3.13/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.13/site-packages/starlette/testclient.py:53
  /Users/srikarjy/resume_projects/concordia/.venv/lib/python3.13/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
SKIPPED [1] tests/unit/test_scripts_import.py:21: scripts need biopython, which is not a project dependency
373 passed, 1 skipped, 2 warnings in 22.33s

