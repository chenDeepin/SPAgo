#!/usr/bin/env bash
# Repeatable check entry for SPAgo (product readiness PROD-05).
#
# Runs, from the current checkout:
#   1. the full backend test suite (needs a reachable PostgreSQL with the
#      RDKit cartridge; unavailable PostgreSQL fails the full check),
#   2. the frontend production build (needs Node >= 20).
#
# Usage: scripts/run_checks.sh [--no-pg]
# Exit code is non-zero if any step fails.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

PY="${ROOT}/services/core/.venv/bin/python"
NODE_BIN="${NODE_BIN:-}"
if [ -z "${NODE_BIN}" ]; then
  for candidate in "$(command -v node)" "$HOME"/.nvm/versions/node/*/bin/node; do
    [ -x "${candidate}" ] || continue
    major="$("${candidate}" -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
    if [ "${major}" -ge 20 ]; then NODE_BIN="${candidate}"; break; fi
  done
fi

echo "== backend tests (services/core) =="
if [ "${1:-}" = "--no-pg" ]; then
  (cd services/core && "${PY}" -m pytest -q \
      tests/test_chemistry.py tests/test_adapters.py tests/test_llm_adapter.py \
      tests/test_llm_contract.py tests/test_m5_ai.py::TestPlanner)
else
  (cd services/core && SPAGO_REQUIRE_TEST_DATABASE=1 "${PY}" -m pytest)
fi

echo "== frontend build (apps/web) =="
if [ -z "${NODE_BIN}" ]; then
  echo "node not found; set NODE_BIN=/path/to/node" >&2
  exit 1
fi
(cd apps/web && "${NODE_BIN}" node_modules/typescript/bin/tsc -p tsconfig.app.json --noEmit \
  && PATH="$(dirname "${NODE_BIN}"):$PATH" npm run build)

if [ "${1:-}" = "--no-pg" ]; then
  echo "== selected backend tests and frontend build passed; database tests not checked =="
else
  echo "== backend suite and frontend build passed =="
fi
