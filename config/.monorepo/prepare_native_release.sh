#!/usr/bin/env bash
# prepare_native_release.sh — resolve packages and index for the release-native workflow.
#
# Called by the "prepare" job in release-native.yml.  Inputs arrive as environment
# variables (set via the workflow's `env:` block); outputs are written to $GITHUB_OUTPUT.
#
# Environment variables:
#   EVENT          — github.event_name ("push" or "workflow_dispatch")
#   REF_NAME       — github.ref_name (tag, e.g. "dissect.util/3.5.0")
#   INPUT_PACKAGES — packages input from workflow_dispatch
#   INPUT_INDEX    — index input from workflow_dispatch
#
# Outputs:
#   packages    — space-separated package names to build
#   index       — target PyPI index (pypi or testpypi)
#   is-native   — "true" if any of the packages is a native project
set -euo pipefail
TOOLING_PYTHON=$(< "$(dirname "$0")/tooling-python")

if [[ "$EVENT" == "push" ]]; then
    # Tag format: <package>/<version> — extract the package name.
    pkg="${REF_NAME%/*}"
    index="pypi"
else
    pkg="$INPUT_PACKAGES"
    index="$INPUT_INDEX"
fi

# Expand "all" to the full list of native projects.
if [[ "$pkg" == "all" ]]; then
    mapfile -t pkgs < <(uv run --python "$TOOLING_PYTHON" .monorepo/native_projects.py)
    pkg="${pkgs[*]}"
fi

# Check whether any of the requested packages is a native project.
mapfile -t native_projects < <(uv run --python "$TOOLING_PYTHON" .monorepo/native_projects.py)
is_native=false
for p in $pkg; do
    if printf '%s\n' "${native_projects[@]}" | grep -qxF "$p"; then
        is_native=true
        break
    fi
done

echo "packages=$pkg" >> "$GITHUB_OUTPUT"
echo "index=$index" >> "$GITHUB_OUTPUT"
echo "is-native=$is_native" >> "$GITHUB_OUTPUT"
