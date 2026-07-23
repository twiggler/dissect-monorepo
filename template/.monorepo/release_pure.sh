#!/usr/bin/env bash
# release_pure.sh — build, publish, and tag pending workspace projects.
#
# Builds an sdist (and for pure-Python projects, a wheel) via `uv build`, publishes via
# `uv publish --skip-existing`, then pushes namespaced git tags.
#
# For native (Rust) projects the binary wheels are expected to already be on PyPI,
# uploaded by the per-platform runners in release-native.yml. This script only adds
# the sdist alongside them; --skip-existing means it won't re-upload wheels.
#
# Usage:
#   .monorepo/release_pure.sh <project> [<project> ...] [--target <production|test>]
#   .monorepo/release_pure.sh all [--target <production|test>]
#
# --target defaults to "production". The role maps to a [[tool.uv.index]] name via
# [tool.monorepo.release] in pyproject.toml. A 'production' release is tagged; a 'test'
# release publishes for upload validation only and is NOT tagged.
#
# Authentication:
#   Local:  export UV_PUBLISH_TOKEN=<token> before running.
#   CI:     uv uses OIDC Trusted Publishing automatically (GitHub Actions / GitLab CI).
set -euo pipefail
TOOLING_PYTHON=$(< "$(dirname "$0")/tooling-python")

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
role="production"
raw_packages=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            shift
            role="$1"
            ;;
        *)
            raw_packages+=("$1")
            ;;
    esac
    shift
done

if [[ ${#raw_packages[@]} -eq 0 ]]; then
    echo "error: specify project names or 'all'" >&2
    exit 1
fi

# Resolve the release role to a concrete package index name.
index=$(uv run --python "$TOOLING_PYTHON" .monorepo/resolve_index.py "$role")

# ---------------------------------------------------------------------------
# Expand "all"
# ---------------------------------------------------------------------------
if [[ "${raw_packages[*]}" == "all" ]]; then
    mapfile -t requested < <(uv run --python "$TOOLING_PYTHON" .monorepo/bump_version.py list-packages)
else
    requested=("${raw_packages[@]}")
fi

# ---------------------------------------------------------------------------
# Filter to pending projects only
# ---------------------------------------------------------------------------
mapfile -t pending_all < <(uv run --python "$TOOLING_PYTHON" .monorepo/bump_version.py pending-releases --names)

to_release=()
for pkg in "${requested[@]}"; do
    if printf '%s\n' "${pending_all[@]}" | grep -qxF "$pkg"; then
        to_release+=("$pkg")
    else
        echo "[skip] $pkg — already released (no pending tag)"
    fi
done

if [[ ${#to_release[@]} -eq 0 ]]; then
    echo "Nothing to release."
    exit 0
fi

echo "Projects to release: ${to_release[*]}"
echo

# ---------------------------------------------------------------------------
# If the dissect meta-project is in the release set, sync its dep pins first
# ---------------------------------------------------------------------------
for pkg in "${to_release[@]}"; do
    if [[ "$pkg" == "dissect" ]]; then
        echo "--- Updating dissect meta-project dependency pins ---"
        uv run --python "$TOOLING_PYTHON" .monorepo/update_meta_deps.py
        echo
        break
    fi
done

# ---------------------------------------------------------------------------
# Build phase — all projects must build before any are published
# ---------------------------------------------------------------------------
echo "=== Build phase ==="
declare -A dist_dirs
for pkg in "${to_release[@]}"; do
    [[ "$pkg" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "error: invalid project name: $pkg" >&2; exit 1; }
    out="dist/${pkg}"
    mkdir -p "$out"
    find "$out" -mindepth 1 -delete
    echo "--- Building $pkg ---"
    uv build --package "$pkg" --out-dir "$out"

    dist_dirs["$pkg"]="$out"
done
echo

# ---------------------------------------------------------------------------
# Collect name/version for each project (needed for tagging)
# ---------------------------------------------------------------------------
declare -A versions
while IFS=' ' read -r name ver; do versions["$name"]="$ver"; done \
    < <(uv run --python "$TOOLING_PYTHON" .monorepo/bump_version.py package-version "${to_release[@]}")

# ---------------------------------------------------------------------------
# Publish phase
# ---------------------------------------------------------------------------
echo "=== Publish phase (target: $role, index: $index) ==="
for pkg in "${to_release[@]}"; do
    echo "--- Publishing $pkg ---"
    uv publish --index "$index" "${dist_dirs[$pkg]}"/*
done
echo

# ---------------------------------------------------------------------------
# Tag + push phase — production releases only
# ---------------------------------------------------------------------------
# Tags are the canonical release ledger (pending-release detection keys off them) and
# they trigger native wheel builds via release-native.yml. Only the production role is a
# real release; a test release is an upload-validation dry run, so it is left untagged.
if [[ "$role" != "production" ]]; then
    echo "Target role '$role' is not production — skipping tag creation (test releases are not tagged)."
    echo
    echo "Published ${#to_release[@]} project(s) to '$index' (no tags)."
    exit 0
fi

echo "=== Tagging ==="
for pkg in "${to_release[@]}"; do
    version="${versions[$pkg]}"
    tag="${pkg}/${version}"
    git tag "$tag"
    git push origin "$tag"
    echo "  tagged and pushed: $tag"
done

echo
echo "Released ${#to_release[@]} project(s)."
