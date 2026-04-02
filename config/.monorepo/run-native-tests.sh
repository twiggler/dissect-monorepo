#!/usr/bin/env bash
# Runs native in-place tests for the affected packages, or all packages when no base ref
# is available. Builds all native extensions first, then delegates to run-tests.sh logic
# with DISSECT_FORCE_NATIVE set (via test-native-all / test-native-affected).
#
# Expected environment variables (set via the step's env: block):
#   BASE_REF   — output from compute-base-ref.sh; empty triggers test-native-all
#   PY_VERSION — Python version from the matrix (e.g. "3.12")

set -euo pipefail

if [[ -z "$BASE_REF" ]]; then
    just test-native-all "$PY_VERSION"
else
    just test-native-affected "$BASE_REF" "$PY_VERSION"
fi
