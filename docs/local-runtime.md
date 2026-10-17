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
