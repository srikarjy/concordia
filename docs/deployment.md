# Free Hugging Face deployment

Concordia can be published as a CPU Docker Space for the saved scientific workspace. The Space is deliberately read-only and serves the deterministic fixture demonstration; it does not download model weights, call Ollama, or claim Evo2 findings.

The current public deployment is [srikarjy025/concordia-colony](https://srikarjy025-concordia-colony.hf.space). It intentionally excludes API credentials, local Qwen artifacts, real Evo2 execution, and State model weights.

## ZeroGPU qualification surface

A separate public Gradio Space, [srikarjy025/concordia-evo2-forward](https://huggingface.co/spaces/srikarjy025/concordia-evo2-forward), contains a bounded GPU capability probe. It accepts no DNA and performs no model inference. The initial measured allocation was an NVIDIA RTX PRO 6000 Blackwell Server Edition MIG instance with 50,868,518,912 bytes of memory, CUDA 12.8, compute capability 12.0, and BF16 support. The immutable summary is recorded in `reports/evo2-zerogpu-hardware-probe.json`.

This measurement establishes candidate capacity only. Its Python 3.10.13 runtime is outside pinned Evo2 0.6.0's Python 3.11/3.12 requirement. Evo2 installation, checkpoint compatibility, causal token shifting, numerical correctness, and forward scoring are all still unverified. The Space must remain restricted to the frozen HBB inputs if a future execution boundary is added; it must never become an arbitrary-sequence public endpoint.

## Build locally

```bash
(cd frontend && npm run build)
docker build -t concordia-workspace .
docker run --rm -p 7860:7860 concordia-workspace
```

Open `http://127.0.0.1:7860`. The container runs `concordia serve-workspace` on port 7860 and builds the workspace from content-addressed local artifacts at startup.

## Publish to a Space

Create an empty Docker Space in your own Hugging Face namespace, set `HF_SPACE_ID` to `namespace/space-name`, then authenticate locally with a token that has write access. Never commit the token.

```bash
hf auth login
hf upload "$HF_SPACE_ID" . \
  --type space \
  --include Dockerfile --include README.md --include LICENSE \
  --include pyproject.toml --include uv.lock --include 'src/**' \
  --include 'frontend/**' --include 'configs/**' --include 'docs/**' \
  --include 'reports/**' \
  --exclude 'frontend/node_modules/**' --exclude 'frontend/dist/**' \
  --exclude '.concordia/**' --exclude 'data/raw/**' \
  --commit-message "Publish reproducible scientific workspace"
```

The Hub CLI requires an authenticated account and network access; this repository cannot infer a namespace or create a public Space without those user-controlled choices. The deployment remains optional and replaceable. A Space running this image is a software demonstration, not a scientific validation environment.
