# Portfolio execution instructions for Codex, Claude, and other contributors

## Objective and approval boundary

Deliver a researcher workflow: validated mutations → traceable predictions →
explicit human decisions → later assay import → revision-specific, verifiable
exports. Demonstrate it with public experimental data and a genuinely executed
local baseline. Keep the existing 1IGV historical replay separately labeled.

The user authorized implementation, downloads, local execution, testing, and
deployment preparation. **Do not deploy a preview or production site, push a
deployment-triggering branch, or change aliases until the user explicitly says
OK to deployment.** Local build success is not Vercel deployment success.

Read this file, `docs/PORTFOLIO_FINISH_PLAN.md`, `docs/installation-and-checks.md`,
the current git diff, and the execution record before continuing. Preserve user
changes. Do not reset the workspace or repeat completed model runs unnecessarily.

## What to build and preserve

1. Local editable review: validated FASTA/CSV, mutation identity checks, source
   units/directions, disagreement flags, protected-position override rationale,
   selected/excluded/deferred decisions, optimistic revision conflicts, assay
   provenance, immutable pre-import decisions, and revision exports.
2. Standalone export verification: every file's bytes and presence, snapshot
   chain, raw inputs, diagnostic records, and exact displayed/downloaded
   revision. Reject missing diagnostics and altered CSV/HTML/FASTA. Verification
   must also work under `python -O`. A replaced verifier can forge local
   consistency; never call this external attestation or an authenticated ledger.
3. Public replay: read-only 1IGV revisions, diagnostic limitation, working
   downloads, benchmark navigation, and a link to the fresh 1PGA execution.
4. Real-data execution: `scripts/run_public_data_review.py` downloads pinned
   public inputs, validates all 930 1PGA variants, trains CPU Ridge, evaluates
   held-out positions against the training-mean baseline, and performs a real
  HTTP create/decision/assay/export sequence against the local server. The
  deterministic source/model/split review ID makes reruns reuse that record;
  it refuses to overwrite a mismatched record. The constant-mean baseline is
  evaluated by RMSE but is not shown as a second candidate-ranking source.
5. Vercel output: static assets only, with the existing rewrites/security
   headers. The editable API and local ML execution are not deployed to Vercel.

Do not expand the project with another model dashboard. Fresh ThermoMPNN,
attribution, independent-protein validation, and authenticated multi-user
uploads are separate work with separate evidence requirements.

## Install and start locally

Use Python 3.11–3.13, Node compatible with the locked Vite version, and npm.
From the repository root:

```sh
uv sync --locked --extra dev --extra virtual-cell --extra postgres
cd frontend
npm ci
npx playwright install chromium
npm run build
cd ..
PYTHONPATH=src .venv/bin/python -m concordia.cli serve-workspace \
  --state-root .concordia/portfolio-local --frontend frontend/dist --port 7860
```

Keep the server running. Open http://127.0.0.1:7860. The full historical 1IGV
regression suite also requires the frozen asset archive described in
`installation-and-checks.md`; its external acquisition remains a separate
release dependency. The static replay and 1PGA baseline do not require that
archive or foundation-model weights.

## Run the real public-data workflow

In a second terminal at the repo root:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_public_data_review.py --fetch
python3 scripts/verify_review_replay.py
```

Omit `--fetch` to reuse locally cached inputs after SHA-256 verification.
The downloader refuses changed inputs and limits each response to 30 MB.

Sources:

- [Tsuboyama v2_230420 on Zenodo](https://zenodo.org/records/7992926),
  `Data_tables_for_figs.zip`, member `dG_extdG_data_Fig1.csv`.
  Published archive MD5: `c4b6a64345e30e1b9e2e40a266d14a68`.
- [RCSB 1PGA](https://www.rcsb.org/structure/1PGA), downloaded FASTA.

Require every named mutation to reproduce its experimental sequence exactly
after removing the documented `SAGGSAGG` terminal flanks. Refuse unexpected
identities, duplicate sequences, nonfinite measurements, or checksum drift.
The target is absolute folding `deltaG` in kcal/mol, **not** mutation `ddG`.

The fixed evaluation split holds out positions divisible by five. Train only
on the remaining positions; use amino-acid counts and Ridge alpha=1, with no
holdout tuning. Preserve all IDs, coefficients, versions, source hashes, and
the mean-baseline comparison. Scripted decisions use predicted order before
assay import; they must be described as illustrative, not researcher decisions.
The editable review shows only the highest, middle, and lowest predicted test
examples; its model metrics still use all 185 held-out variants. The constant
mean baseline is a regression comparator, not a competing candidate ranking.

Outputs are in `frontend/public/public-data-review/`: execution JSON, measured
dataset, HTML review, and a bundle containing the complete history plus model
and data provenance. UUIDs and timestamps vary on rerun; fixed-data model
metrics should remain numerically equivalent. The 1IGV replay is byte-stable.

## Test matrix and commands

| Surface | Required evidence |
| --- | --- |
| Input validation | Wrong WT, duplicate mutant, unchanged residue, range, CSV columns, units/directions rejected |
| Decisions | Protected positions require override; select/exclude/defer persist; stale revision returns 409 |
| Assays | Context required; duplicates refused; pre-import decisions remain unchanged |
| Exports | Correct revision; formula escaping; changed/missing files rejected, including with `-O` |
| Real data | Pinned source hashes; 930 mapped unique mutants; disjoint train/test positions; baseline metrics; real HTTP result |
| Local browser | Complete example, decisions, assay import, export; no hosted requests |
| Public browser | Read-only state; revisions 1 and 7; diagnostic record; downloads; real-data result link; no API writes |
| Deployment build | Exact Vercel build command; archive verification; secret/path sanitizer; rewrites and CSP |
| Broader software | Full Python suite, Ruff, all configured mypy targets, workspace browser suite |

```sh
PYTHONPATH=src .venv/bin/pytest tests/unit/test_review_workflow.py tests/integration/test_review_api.py
make verify
PYTHONPATH=src .venv/bin/python scripts/build_review_replay.py
python3 scripts/verify_review_replay.py
python3 scripts/build_static_stability.py
cd frontend
npm run check
npm run build
npm run test:all
cd ..
python3 scripts/serve_static_preview.py --port 4175
```

Keep the last process running; open http://127.0.0.1:4175/review and
http://127.0.0.1:4175/public-data-review/index.html. Playwright's temporary server
stops when tests finish; it is not the persistent demo server.

For manual acceptance: inspect mobile/desktop, change replay revisions, compare
CSV identities, open the real-data report, extract a bundle and run
`python3 -I verify.py`. Alter the shortlist or remove diagnostic files and require
a nonzero exit. The browser must not show uncaught errors. Save screenshots and
exact command results; distinguish fresh checks from historical evidence.

## Vercel deployment, only after explicit OK

The committed `vercel.json` selects:

- Repository root as project root; framework preset Other.
- Build command: `python3 scripts/build_static_stability.py`.
- Output directory: `frontend/dist-stability`.
- Routes `/`, `/review`, `/stability`; frozen public assets under their paths.

The build verifies all exported bundles before shipping. It uses committed
results and does not retrain models or download scientific data. Do not inject
provider keys into frontend variables. The saved replay requires no accounts.
The stability surface has optional existing remote integrations; these are not
verified by the local review demonstration.

After approval, inspect the linked project/account without exposing tokens,
confirm the intended production domain, then deploy a preview from the reviewed
tree (`vercel deploy`). Run the public browser checks against that URL and
download/verify the deployed ZIP; compare its SHA-256 with the local approved
bundle. Check `/`, `/review`, `/stability`, `/public-data-review/index.html`,
404 for absent APIs, CSP headers, mobile layout, and console/network errors.
Only promote the verified deployment within the approved scope. Record its URL,
deployment ID, source revision, hashes, and post-deploy results. Never claim
remote CI passed without reading that run.

```sh
cd frontend
CONCORDIA_PUBLIC_BASE_URL=https://THE_APPROVED_DEPLOYMENT_URL npm run test:public
```

This mode tests the given deployment without starting a local web server.

Official references: [Vercel build configuration](https://vercel.com/docs/builds/configure-a-build),
[local build](https://vercel.com/docs/cli/build),
[deploy CLI](https://vercel.com/docs/cli/deploy).

## Completion report

Report local URL, source URLs, train/test counts, metrics and baseline, decision
history, exported hashes, test results, unresolved limitations, and deployment
status. Do not describe this single-protein retrospective baseline as clinical,
biological, or general predictor validation. Wait for explicit deployment OK.
