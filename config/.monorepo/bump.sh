#!/usr/bin/env bash
# Bump the minor version of one or more workspace packages.
# Usage: bump.sh <package> [<package> ...]  |  bump.sh all
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "error: specify package names or 'all'" >&2
    exit 1
fi

if [[ "$1" == "all" ]]; then
    mapfile -t targets < <(
        for f in projects/*/pyproject.toml; do
            [[ "$f" == *"/template/"* ]] && continue
            grep '^name = ' "$f" | sed 's/name = "\(.*\)"/\1/'
        done
    )
else
    targets=("$@")
fi

# Validate: a package already in the pending list has no release tag for its
# current version — bumping it would silently skip a release.
mapfile -t pending < <(.monorepo/pending_releases.sh --names)

double_bumps=()
for pkg in "${targets[@]}"; do
    if printf '%s\n' "${pending[@]}" | grep -qxF "$pkg"; then
        double_bumps+=("$pkg")
    fi
done

if [[ ${#double_bumps[@]} -gt 0 ]]; then
    echo "error: the following packages have no release tag for their current version." >&2
    echo "Release them first, or create the tags manually." >&2
    echo >&2
    for pkg in "${double_bumps[@]}"; do
        echo "  $pkg" >&2
    done
    exit 1
fi

uv run --python ">=3.12" .monorepo/bump_version.py "${targets[@]}"
