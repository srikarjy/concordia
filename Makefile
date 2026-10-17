.PHONY: demo serve test frontend benchmark verify space-lock

# Offline, no network, exits 0: runs the genomic evidence pipeline on the bundled fixture.
demo:
	uv sync --extra dev --extra virtual-cell --extra postgres --extra scientist --extra xai
	.venv/bin/concordia genomic-demo --output .concordia/genomic-demo
	@echo "demo OK: .concordia/genomic-demo/manifest.json"

# Interactive workspace at http://127.0.0.1:7860
serve: frontend
	uv sync --extra dev --extra virtual-cell --extra postgres --extra scientist --extra xai
	.venv/bin/concordia serve-workspace --state-root .concordia/workspace --frontend frontend/dist --port 7860

frontend:
	cd frontend && npm ci && npm run build

test:
	uv sync --extra dev --extra virtual-cell --extra postgres --extra scientist --extra xai
	.venv/bin/pytest -q && .venv/bin/ruff check src tests && .venv/bin/mypy src/concordia
	cd frontend && npm ci && npm run build && npm test

verify:
	set -e; \
	.venv/bin/ruff check .; \
	.venv/bin/mypy --strict src/concordia/stability; \
	.venv/bin/pytest -q; \
	.venv/bin/mypy .

benchmark:
	uv sync --extra dev
	.venv/bin/concordia benchmark --suite all --output reports/benchmark-local.json

# Resolve the Space image's dependencies to exact versions with hashes, for the
# deployment target rather than this machine. The Dockerfile installs only this file.
space-lock:
	uv pip compile requirements-space.txt --generate-hashes --no-annotate --no-header \
	  --python-platform x86_64-unknown-linux-gnu --python-version 3.13 \
	  -o requirements-space.lock.txt
