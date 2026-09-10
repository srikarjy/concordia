# Free Hugging Face deployment

Concordia can be published as a CPU Docker Space for the saved scientific workspace. The Space is deliberately read-only and serves the deterministic fixture demonstration; it does not download model weights, call Ollama, or claim Evo2 findings.

The current public deployment is [srikarjy025/concordia-colony](https://srikarjy025-concordia-colony.hf.space). It intentionally excludes API credentials, local Qwen artifacts, real Evo2 execution, and State model weights.

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
  --include Dockerfile README.md LICENSE pyproject.toml uv.lock src frontend \
  --exclude 'frontend/node_modules/**' --exclude 'frontend/dist/**' \
  --exclude '.concordia/**' --exclude 'data/raw/**' \
  --commit-message "Publish reproducible scientific workspace"
```

The Hub CLI requires an authenticated account and network access; this repository cannot infer a namespace or create a public Space without those user-controlled choices. The deployment remains optional and replaceable. A Space running this image is a software demonstration, not a scientific validation environment.
