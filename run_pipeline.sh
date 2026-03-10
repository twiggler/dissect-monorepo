#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run migration and post-processing steps in order.
# Usage: ./run_pipeline.sh

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)

run() {
  echo
  echo "=== $* ==="
  if ! "$@"; then
    echo "Command failed: $*" >&2
    exit 1
  fi
}

# 1. migrate.sh (always use bash)
echo "Running migrate.sh"
run bash "$SCRIPT_DIR/migrate.sh"

# 2. decouple_versions.sh (shell)
echo "Running decouple_versions.sh"
run bash "$SCRIPT_DIR/decouple_versions.sh"

# 3. internal_deps.py (python via uv)
echo "Running internal_deps.py"
run uv run "$SCRIPT_DIR/internal_deps.py"

# 4. centralize_deps.py (python via uv)
echo "Running centralize_deps.py"
run uv run "$SCRIPT_DIR/centralize_deps.py"

# 5. centralize_ruff_config.py (python via uv)
echo "Running centralize_ruff_config.py"
run uv run "$SCRIPT_DIR/centralize_ruff_config.py"

# 6. update_project_src_layout.py (python via uv)
echo "Running update_project_src_layout.py"
run uv run "$SCRIPT_DIR/update_project_src_layout.py"

echo
echo "Pipeline complete."
