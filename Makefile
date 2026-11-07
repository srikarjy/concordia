.PHONY: demo serve test frontend benchmark verify typecheck build-stability-static space-lock

PYTHON_ENV ?= .venv

# Offline, no network, exits 0: runs the genomic evidence pipeline on the bundled fixture.
demo:
	uv sync --locked --extra dev --extra virtual-cell --extra postgres
	.venv/bin/concordia genomic-demo --output .concordia/genomic-demo
	@echo "demo OK: .concordia/genomic-demo/manifest.json"

# Interactive workspace at http://127.0.0.1:7860
serve: frontend
	uv sync --locked --extra dev --extra virtual-cell --extra postgres
	.venv/bin/concordia serve-workspace --state-root .concordia/workspace --frontend frontend/dist --port 7860

frontend:
	cd frontend && npm ci && npm run build

build-stability-static:
	python3 scripts/build_static_stability.py

test:
	uv sync --locked --extra dev --extra virtual-cell --extra postgres
	$(MAKE) verify
	cd frontend && npm ci && npm run build && npm run test:all

verify:
	$(PYTHON_ENV)/bin/python scripts/check_stability_assets.py
	$(PYTHON_ENV)/bin/ruff check .
	$(MAKE) typecheck
	$(PYTHON_ENV)/bin/pytest -q

# Deployment directories have independent modules named app; check each separately.
typecheck:
	$(PYTHON_ENV)/bin/mypy --strict src/concordia/stability
	$(PYTHON_ENV)/bin/mypy --explicit-package-bases src/concordia scripts tests
	$(PYTHON_ENV)/bin/mypy deploy/hf-evo2-worker
	$(PYTHON_ENV)/bin/mypy deploy/hf-structure-gateway
	$(PYTHON_ENV)/bin/mypy deploy/hf-thermompnn-space

benchmark:
	uv sync --extra dev
	.venv/bin/concordia benchmark --suite all --output reports/benchmark-local.json

# Resolve the Space image's dependencies to exact versions with hashes, for the
# deployment target rather than this machine. The Dockerfile installs only this file.
space-lock:
	uv pip compile requirements-space.txt --generate-hashes --no-annotate --no-header \
	  --python-platform x86_64-unknown-linux-gnu --python-version 3.13 \
	  -o requirements-space.lock.txt
