#!/usr/bin/env bash
# Runs tests for the affected packages, or all packages when no base ref is available.
#
# Expected environment variables (set via the step's env: block):
#   BASE_REF   — output from compute-base-ref.sh; empty triggers test-all
#   PY_VERSION — Python version from the matrix (e.g. "3.12")

set -euo pipefail

if [[ -z "$BASE_REF" ]]; then
    just test-all "$PY_VERSION"
else
    just test-affected "$BASE_REF" "$PY_VERSION"
fi
