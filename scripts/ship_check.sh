#!/usr/bin/env bash
# Pre-flight checks to run before sharing the repository.
# Usage: scripts/ship_check.sh [branch]   (defaults to the current branch)
set -euo pipefail

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
ORIGIN="$(git remote get-url origin)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [ -n "${PIDS:-}" ] && kill $PIDS 2>/dev/null || true' EXIT

echo "=== 1. Clean clone of $BRANCH, offline demo ==="
git clone --quiet --branch "$BRANCH" "$ORIGIN" "$TMP/concordia"
cd "$TMP/concordia"
[ ! -d .concordia ] || { echo "FAIL: .concordia ships in the repository"; exit 1; }
make demo
echo "OK"

echo "=== 2. Tests, lint, types, frontend ==="
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src/concordia
(cd frontend && npm ci --silent && npm run build --silent && npm test --silent)
echo "OK"

echo "=== 3. No internal 'Phase N' wording in user-facing text ==="
if grep -rn "Phase [0-9]" frontend/src README.md; then
  echo "FAIL: 'Phase N' found in user-facing text"; exit 1
fi
echo "OK"

echo "=== 4. Public tool contract is GET-only ==="
.venv/bin/concordia serve-workspace --state-root "$TMP/state" --frontend frontend/dist --port 7899 >/dev/null 2>&1 &
PIDS="$!"
until curl -s -o /dev/null http://127.0.0.1:7899/health; do sleep 1; done
NON_GET=$(curl -s http://127.0.0.1:7899/api/tools/openapi.json \
  | jq -r '.paths | to_entries[] | .key as $p | .value | keys[] | select(. != "get") | "\(. | ascii_upcase) \($p)"')
if [ -n "$NON_GET" ]; then echo "FAIL: non-GET methods in public contract:"; echo "$NON_GET"; exit 1; fi
curl -s http://127.0.0.1:7899/api/frameworks | jq -e '.frameworks | length > 0' >/dev/null
echo "OK"

echo "=== 5. README ==="
WORDS=$(sed -n '/^# /,/^## License/p' README.md | wc -w | tr -d ' ')
echo "README body: $WORDS words (target under 900)"
[ "$WORDS" -le 900 ] || { echo "FAIL: README too long"; exit 1; }
grep -q "RMSD\|Antibody RMSD" README.md || { echo "FAIL: no benchmark results in README"; exit 1; }
echo "OK"

echo "=== All ship checks passed ==="
