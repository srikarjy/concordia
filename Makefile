.PHONY: demo serve test frontend benchmark

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

benchmark:
	uv sync --extra dev
	.venv/bin/concordia benchmark --suite all --output reports/benchmark-local.json
