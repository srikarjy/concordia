# Free Hugging Face deployment

Concordia can be published as a CPU Docker Space for the saved scientific workspace. The Space is deliberately read-only and serves the deterministic fixture demonstration; it does not download model weights, call Ollama, or claim Evo2 findings. The interface separates claim investigation, bounded sequence replay, colony evolution, and provenance into focused views instead of exposing a mutable research backend.

The current public deployment is [srikarjy025/concordia-colony](https://srikarjy025-concordia-colony.hf.space). It intentionally excludes API credentials, local Qwen artifacts, real Evo2 execution, and State model weights.

Its curated OpenAPI tool document is served from `/api/tools/openapi.json`. The
contract contains six read-only evidence-inspection operations and is safe to
import into OpenAPI-compatible clients. It does not expose the mutable local run
API, arbitrary sequences, CellForge execution, or either model runtime. See
[`tool-integration.md`](tool-integration.md).
The same deployment serves `/privacy` for clients that require a public privacy
notice.

The sequence sandbox runs entirely in the loaded browser state. It selects from
144 persisted fixture counterfactuals, performs no mutation API call, and labels
every score as non-scientific. It is a safe interaction demonstration, not an
Evo2 execution service and not a general-purpose code sandbox.

## ZeroGPU qualification surface

A separate public Gradio Space, [srikarjy025/concordia-evo2-forward](https://huggingface.co/spaces/srikarjy025/concordia-evo2-forward), contains bounded hardware and runtime qualification endpoints. It accepts no DNA and performs no model inference. The initial measured allocation was an NVIDIA RTX PRO 6000 Blackwell Server Edition MIG instance with 50,868,518,912 bytes of memory, CUDA 12.8, compute capability 12.0, and BF16 support. The immutable summary is recorded in `reports/evo2-zerogpu-hardware-probe.json`.

Space revision `390013f35bef0874bbc9a24d49909d0ea14c6b18` passed the no-input runtime boundary with Python 3.12.12, PyTorch 2.8.0+cu128, Evo2 0.6.0 from the pinned source revision, Vortex 1.1.0, and a SHA-256-pinned FlashAttention 2.8.3 wheel. It also verified the 13,766,621,200-byte checkpoint and selected installed source files without deserializing model data. The preceding missing-FlashAttention import failure is retained in `reports/evo2-zerogpu-runtime-qualification.json`.

This result establishes artifact and import compatibility only. Checkpoint deserialization, model loading, FlashAttention execution on compute capability 12.0, causal token shifting, numerical correctness, and forward scoring remain unverified. The Space must remain restricted to the frozen HBB inputs if an execution boundary is added; it must never become an arbitrary-sequence public endpoint.

## Build locally

```bash
(cd frontend && npm run build)
docker build -t concordia-workspace .
docker run --rm -p 7860:7860 concordia-workspace
```

Open `http://127.0.0.1:7860`. The container runs `concordia serve-workspace` on port 7860 and builds the workspace from content-addressed local artifacts at startup.
The runtime process uses a dedicated non-root user and can write only its local
`.concordia` state directory within the application tree.

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
