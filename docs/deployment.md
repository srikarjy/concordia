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

## Interactive endpoints and their environment variables

The deployed workspace is mostly read-only (see above), but exposes five
rate-limited, non-tool endpoints that make real outbound calls or execute
real local code on a visitor's request. Each is controlled by an environment
variable; omitting it makes that specific endpoint fail closed with a `503`
rather than silently degrading:

| Variable | Enables | Behavior when unset |
| --- | --- | --- |
| `NVIDIA_API_KEY` | `POST /nvidia/evo2/generate`, `/nvidia/boltz/predict`, `/nvidia/esmfold/predict` | `503` |
| `CONCORDIA_EVO2_FORWARD_SPACE_URL` | `POST /nvidia/evo2/forward` (points at a deployed `deploy/hf-evo2-worker` Space) | `503` |
| `CONCORDIA_TRUST_PROXY_HEADERS=1` | Honors `X-Forwarded-For` for per-client rate limiting | Falls back to the raw socket address, which is wrong behind a proxy (see below) |
| `CONCORDIA_DATABASE_URL` | Persists rate limits, response caches, and job history to Postgres instead of local SQLite | Everything still works, but state resets on every redeploy/restart |

`POST /colony/run` needs no variable — it always runs the deterministic
fixture executor locally.

**Set `CONCORDIA_TRUST_PROXY_HEADERS=1` on Hugging Face Spaces.** A Space
sits behind HF's own reverse proxy, so every request's raw socket address is
the proxy's address, not the visitor's — without this flag, every visitor
shares one rate-limit bucket.

### Persisting state with Supabase (optional)

A Space's local filesystem is wiped on every redeploy and restart. Setting
`CONCORDIA_DATABASE_URL` to a Postgres connection string (a free Supabase
project works well) makes `evo2_generation_gateway.py`, `esmfold_gateway.py`,
`boltz_gateway.py`, `evo2_forward_queue.py`, and the colony-run rate limiter
all use `genomics/postgres_backend.py` instead of their local SQLite files —
see each module's docstring. Nothing else changes; this is purely a
persistence upgrade for the five interactive endpoints above, not the core
run/colony ledgers, which remain intentionally local per this project's
zero-cost, local-first design.

To set it up:

1. In a Supabase project, run the migration that creates
   `concordia_rate_limit_requests`, `concordia_result_cache`, and
   `concordia_forward_jobs` (three tables, namespaced by a `concordia_`
   prefix so they coexist safely with any other tables in the same project).
   The exact SQL is in this project's own migration history under the name
   `create_concordia_interactive_state_tables`.
2. From the Supabase dashboard, go to Project Settings → Database →
   Connection string, and copy the **Transaction pooler** URI (port 6543) —
   not the direct connection — since Spaces' outbound networking is IPv4
   and the pooler supports that; the direct host may not.
3. Set `CONCORDIA_DATABASE_URL` to that URI as a Space secret (never commit
   it). Supabase's free tier is sufficient for this workload.

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
  --include 'reports/**' --include requirements-space.txt \
  --exclude 'frontend/node_modules/**' --exclude 'frontend/dist/**' \
  --exclude '.concordia/**' --exclude 'data/raw/**' \
  --exclude '**/__pycache__/**' \
  --commit-message "Publish reproducible scientific workspace"
```

The Hub CLI requires an authenticated account and network access; this repository cannot infer a namespace or create a public Space without those user-controlled choices. The deployment remains optional and replaceable. A Space running this image is a software demonstration, not a scientific validation environment.

### Sequence-retention migration

Interactive request artifacts created before the metadata-only provenance update retained the
submitted sequence text. Deploy the updated image with a fresh or rotated artifact volume; do not
copy an older `artifacts/sha256` tree into the new deployment. The standard Hugging Face Space
configuration uses ephemeral local storage, so a clean rebuild provides this rotation. If a custom
persistent volume is attached, archive or remove the legacy volume under the deployer's data-
retention procedure before exposing the updated service. Provider responses and cached derived
outputs remain retained as described by `/privacy` and may reflect information from the submitted
sequence.
