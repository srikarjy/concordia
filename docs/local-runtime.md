# Local model setup

Build the UI with `cd frontend && npm run build`. From the repository root,
start the configured localhost app with:

```sh
.venv/bin/python scripts/serve_local.py
```

The app serves at http://127.0.0.1:7861. The launcher enables Concordia's
local-only Ollama call guard, loads the existing Hugging Face login for the
forward worker, and preserves workspace data in `.concordia/workspace`.

## NVIDIA hosted inference

Obtain a developer API key using **Get API Key** at https://build.nvidia.com.
Supply it in your terminal, not chat:

```sh
.venv/bin/python scripts/serve_local.py --configure-nvidia
```

Input is hidden. The key is saved in `.concordia/nvidia-api-key` with mode
0600, under a Git-ignored directory. Restart the launcher after configuration.
An existing `NVIDIA_API_KEY` environment variable takes precedence. Configuration
presence does not verify provider authentication, quota, or model entitlement;
a successful real request is still required.

## Ollama and training

The configured local assistant is `qwen3:1.7b`. Verify its installed checkpoint:

```sh
OLLAMA_NO_CLOUD=1 .venv/bin/concordia doctor
```

Run the actual local scientist workflow:

```sh
OLLAMA_NO_CLOUD=1 .venv/bin/concordia qwen-colony-demo --model qwen3:1.7b
```

This runs inference and tool orchestration; it does not train model weights.
The UI's colony simulation is a separate deterministic fixture.
Local protein training uses `concordia-protein-baseline` with
`protein_composition_ridge_v1` on a frozen measured campaign dataset. It trains
a CPU ridge baseline. BioNeMo training still requires a configured external
training service. Fine-tuning Qwen requires a training dataset and a separate
trainer, after which compatible weights can be imported into Ollama.

## Measured-stability page

Build once with `npm run build --prefix frontend`, then run:

```sh
PYTHONPATH=src .venv/bin/python -m concordia.cli serve-workspace \
  --state-root .concordia/workspace --frontend frontend/dist --port 7860
```

Open `http://localhost:7860/stability.html`. On localhost the page scores through
`POST /api/stability/score` using the frozen local model artifacts. No Hugging Face
or NVIDIA request is needed for stability scoring. Non-local deployments retain
the hosted scoring endpoint. `VITE_STABILITY_API_ROOT` can explicitly override it.
The Vite development server also proxies this API path to port 7860.

Private protein uploads and authenticated structure prediction still use the
configured Supabase service; they are not offline substitutes. Email redirects
preserve the current page path, which must be allowed by the auth service.

After building, verify the real local browser-to-engine path with
`cd frontend && npm test -- --config=playwright.local.config.ts`. This test uses
isolated temporary state and port 7864, and checks that no hosted requests occur.
