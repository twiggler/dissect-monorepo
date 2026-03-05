#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run migration and post-processing steps in order.
# Usage: ./run_pipeline.sh

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

run() {
  echo
  echo "=== $* ==="
  if ! "$@"; then
    echo "Command failed: $*" >&2
    exit 1
  fi
}

echo "Running pipeline from: $ROOT_DIR"

# 1. migrate.sh (always use bash)
echo "Running migrate.sh via bash"
run bash dissect-monorepo-scripts/migrate.sh

# 2. decouple_versions.sh (shell)
echo "Running decouple_versions.sh"
run bash dissect-monorepo-scripts/decouple_versions.sh

# 3. internal_deps.py (python via uv)
echo "Running internal_deps.py via 'uv run'"
run uv run dissect-monorepo-scripts/internal_deps.py

# 4. centralize_deps.py (python via uv)
echo "Running centralize_deps.py via 'uv run'"
run uv run dissect-monorepo-scripts/centralize_deps.py

# 5. centralize_ruff_config.py (python via uv)
echo "Running centralize_ruff_config.py via 'uv run'"
run uv run dissect-monorepo-scripts/centralize_ruff_config.py

echo
echo "Pipeline complete."
