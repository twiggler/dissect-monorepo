#!/usr/bin/env bash
# release.sh — build, publish, and tag pending workspace packages.
#
# Usage:
#   .monorepo/release.sh <package> [<package> ...] [--index <name>]
#   .monorepo/release.sh all [--index <name>]
#
# --index defaults to "pypi". Use "--index testpypi" for TestPyPI.
#
# Authentication:
#   Local:  export UV_PUBLISH_TOKEN=<token> before running.
#   CI:     uv uses OIDC Trusted Publishing automatically (GitHub Actions / GitLab CI).
set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
index="pypi"
raw_packages=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --index)
            shift
            index="$1"
            ;;
        *)
            raw_packages+=("$1")
            ;;
    esac
    shift
done

if [[ ${#raw_packages[@]} -eq 0 ]]; then
    echo "error: specify package names or 'all'" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Expand "all"
# ---------------------------------------------------------------------------
if [[ "${raw_packages[*]}" == "all" ]]; then
    mapfile -t requested < <(
        for f in projects/*/pyproject.toml; do
            [[ "$f" == *"/template/"* ]] && continue
            grep '^name = ' "$f" | sed 's/name = "\(.*\)"/\1/'
        done
    )
else
    requested=("${raw_packages[@]}")
fi

# ---------------------------------------------------------------------------
# Filter to pending packages only
# ---------------------------------------------------------------------------
mapfile -t pending_all < <(.monorepo/pending_releases.sh --names)

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

echo "Packages to release: ${to_release[*]}"
echo

# ---------------------------------------------------------------------------
# If the dissect meta-package is in the release set, sync its dep pins first
# ---------------------------------------------------------------------------
for pkg in "${to_release[@]}"; do
    if [[ "$pkg" == "dissect" ]]; then
        echo "--- Updating dissect meta-package dependency pins ---"
        uv run .monorepo/update_meta_deps.py
        echo
        break
    fi
done

# ---------------------------------------------------------------------------
# Build phase — all packages must build before any are published
# ---------------------------------------------------------------------------
echo "=== Build phase ==="
declare -A dist_dirs
for pkg in "${to_release[@]}"; do
    [[ "$pkg" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "error: invalid package name: $pkg" >&2; exit 1; }
    out="dist/${pkg}"
    mkdir -p "$out"
    find "$out" -mindepth 1 -delete
    echo "--- Building $pkg ---"
    uv build --package "$pkg" --out-dir "$out"
    dist_dirs["$pkg"]="$out"
done
echo

# ---------------------------------------------------------------------------
# Collect name/version for each package (needed for tagging)
# ---------------------------------------------------------------------------
declare -A versions
for f in projects/*/pyproject.toml; do
    [[ "$f" == *"/template/"* ]] && continue
    name=$(grep -m1 '^name\s*=' "$f" | sed 's/name\s*=\s*"\(.*\)"/\1/')
    version=$(grep -m1 '^version\s*=' "$f" | sed 's/version\s*=\s*"\(.*\)"/\1/')
    [[ -n "$name" && -n "$version" ]] && versions["$name"]="$version"
done

# ---------------------------------------------------------------------------
# Publish phase
# ---------------------------------------------------------------------------
echo "=== Publish phase (index: $index) ==="
for pkg in "${to_release[@]}"; do
    echo "--- Publishing $pkg ---"
    uv publish --skip-existing --index "$index" "${dist_dirs[$pkg]}"/*
done
echo

# ---------------------------------------------------------------------------
# Tag + push phase
# ---------------------------------------------------------------------------
echo "=== Tagging ==="
for pkg in "${to_release[@]}"; do
    version="${versions[$pkg]}"
    tag="${pkg}/${version}"
    git tag "$tag"
    git push origin "$tag"
    echo "  tagged and pushed: $tag"
done

echo
echo "Released ${#to_release[@]} package(s)."
