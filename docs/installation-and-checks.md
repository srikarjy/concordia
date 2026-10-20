# Installation and checks

Run source-checkout commands from the repository root. Keep the published lock
files; a developer environment containing every optional model package is not
the CI environment.

| Profile | Installation | Scope |
| --- | --- | --- |
| Base runtime | `uv sync --locked` | Review/API and recorded fixture workspace; includes Biopython. No Torch/Transformers. |
| CI / local checks | `uv sync --locked --extra dev --extra virtual-cell --extra postgres` | Python tests, lint, typing, AnnData and Postgres adapter coverage. |
| ESM computation | Add `--extra esm` to the required profile | Actual embedding/zero-shot inference; large model assets are separate. |
| Optional workflows | Add `--extra scientist` or `--extra xai` when used | Ollama client or molecular SHAP. Not prerequisites for cached uncertainty evaluation. |

For a disposable installation without changing `.venv`:

```sh
UV_PROJECT_ENVIRONMENT=/tmp/concordia-checks uv sync --locked --extra dev --extra virtual-cell --extra postgres
make verify PYTHON_ENV=/tmp/concordia-checks
cd frontend
npm ci
npm run build
CONCORDIA_TEST_PYTHON=/tmp/concordia-checks/bin/python npm run test:all
```

`make typecheck` checks the main package, all current scripts and tests with
explicit roots, then each deployment directory independently. This avoids
collisions between unrelated `app.py` modules. All checks are blocking; no
whole-tree `continue-on-error` fallback remains. GPU/hosted deployment runtime
execution is outside these static checks.

Browser tests use separate temporary state directories for each invocation.
The default suite covers the historical workspace; `test:local` covers writable
local reviews, replay, and frozen stability execution; `test:public` covers the
static build with the rewrites and CSP from `vercel.json`. The preview helper
implements exact static rewrites and headers only, not the complete Vercel
platform. No browser test is evidence of a deployment.

## Frozen 1IGV prerequisites and T2 boundary

```sh
python3 scripts/check_stability_assets.py
```

This is an **availability check**, not integrity verification. Full regression
tests and the local stability browser test need every file declared in
`data/manifests/tsuboyama_stability_assets_v1.json`:

- `data/manifests/tsuboyama_rule2_manifest_v3.json`
- `data/processed/tsuboyama_v2_230420_normalized.csv`
- `data/processed/tsuboyama_esm2_site_embeddings.parquet`
- `data/processed/tsuboyama_ensemble_artifacts.joblib`
- `data/processed/tsuboyama_production_ranker.json`
- `data/processed/tsuboyama_t2_recalibration.json`
- `data/processed/tsuboyama_uncertainty_metrics.json`
- `data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb`

The seven non-manifest files are ignored local scientific assets in the current
checkout. A fresh clone does not supply them. `scripts/package_stability_assets.py`
can create a digest-verified local `tar.gz` from a trusted root:

```sh
PYTHONPATH=src .venv/bin/python scripts/package_stability_assets.py \
  --source-root /path/to/verified/concordia-assets \
  --output /path/to/concordia-stability-assets-v1.tar.gz
```

Extract the archive at the checkout root before invoking `make verify`; serving
then verifies every size and SHA-256 before opening serialized artifacts. The
archive has not been published yet. Its release needs a reviewed hosting target
and confirmation that the derived assets may be redistributed. Until then,
remote fresh-clone CI is intentionally blocked at preflight rather than skipping
tests or silently rebuilding a model. Do not deserialize an untrusted replacement
joblib file. Serving loads the frozen calibration and does not recalibrate it.

The base review workflow and static replay do not require those model files.
The review example is included in the wheel; the static page uses committed
saved evidence plus the existing replay assets. A wheel alone does not include
the frontend or frozen scientific model assets. Supply a separately built
frontend directory when serving the browser UI.

## Public and local routes

`npm run build` produces `frontend/dist` with local review at `/`, stability
at `/stability.html`, and the historical workspace at `/workspace.html`.
Writable review API access retains the loopback and same-origin checks.

`python3 scripts/build_static_stability.py` produces `frontend/dist-stability`
with read-only review at `/` and `/review`, plus stability at `/stability` or
`/stability.html`. The public build fixes replay mode at compile time, including
when previewed on localhost. Review export links use bundled files; the static
review makes no review API calls. The historical workspace link is omitted
from this public bundle because its server API is not deployed there.

Public protein-account and hosted scoring integrations retain their existing
configuration and boundaries. T1 does not prove those remote services work.
Local browser tests intercept provider interactions where applicable and do
not authorize hosted biology inference.

## Installed-wheel smoke check

```sh
uv build --out-dir /tmp/concordia-dist
uv export --frozen --no-emit-project --no-hashes -o /tmp/concordia-base.txt
uv venv /tmp/concordia-wheel
uv pip install --python /tmp/concordia-wheel/bin/python -r /tmp/concordia-base.txt /tmp/concordia-dist/concordia_xai-0.1.0-py3-none-any.whl
cp scripts/check_installed_wheel.py /tmp/concordia-wheel-smoke.py
cd /tmp
/tmp/concordia-wheel/bin/python concordia-wheel-smoke.py
```

This checks the actual non-editable package, required Bio import, packaged
example, local review creation, and ZIP export from outside the checkout. It
does not execute a model or validate biological predictions.
