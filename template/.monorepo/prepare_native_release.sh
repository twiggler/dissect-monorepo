#!/usr/bin/env bash
# prepare_native_release.sh — resolve projects and index for the release-native workflow.
#
# Called by the "prepare" job in release-native.yml.  Inputs arrive as environment
# variables (set via the workflow's `env:` block); outputs are written to $GITHUB_OUTPUT.
#
# Environment variables:
#   EVENT          — github.event_name ("push" or "workflow_dispatch")
#   REF_NAME       — github.ref_name (tag, e.g. "dissect.util/3.5.0")
#   INPUT_PACKAGES — projects input from workflow_dispatch
#   INPUT_TARGET   — release role input from workflow_dispatch (production/test)
#
# Outputs:
#   packages    — space-separated project names to build
#   index       — target index name (resolved from the release role)
#   target      — release role (production/test)
#   is-native   — "true" if any of the projects is a native project
set -euo pipefail
TOOLING_PYTHON=$(< "$(dirname "$0")/tooling-python")

if [[ "$EVENT" == "push" ]]; then
    # Tag format: <project>/<version> — extract the project name.
    # Tags are only pushed for production releases, so this path is always production.
    pkg="${REF_NAME%/*}"
    target="production"
else
    pkg="$INPUT_PACKAGES"
    target="$INPUT_TARGET"
fi

# Resolve the release role to a concrete package index name.
index=$(uv run --python "$TOOLING_PYTHON" .monorepo/resolve_index.py "$target")

# Expand "all" to the full list of native projects.
if [[ "$pkg" == "all" ]]; then
    mapfile -t pkgs < <(uv run --python "$TOOLING_PYTHON" .monorepo/native_projects.py)
    pkg="${pkgs[*]}"
fi

# Check whether any of the requested projects is a native project.
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
echo "target=$target" >> "$GITHUB_OUTPUT"
echo "is-native=$is_native" >> "$GITHUB_OUTPUT"
