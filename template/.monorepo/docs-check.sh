#!/usr/bin/env bash
# Build the Sphinx API-reference docs for every project that has a tests/_docs/
# directory and fail if sphinx-build emits any warnings.
#
# All workspace packages must already be installed as editable (--all-packages)
# so that autoapi can resolve imports across sibling projects. This is handled
# by the caller (just docs-check / CI step).

set -uo pipefail

failed=()

for d in projects/*/; do
    [[ -d "$d/tests/_docs" ]] || continue
    pkg=$(basename "$d")
    sourcedir="$d/tests/_docs"
    builddir="$d/tests/_docs/build"
    echo "--- docs-check: $pkg ---"
    if ! sphinx-build -b html -jauto \
            -w "$builddir/warnings.log" \
            --fail-on-warning \
            "$sourcedir" "$builddir/html"; then
        failed+=("$pkg")
    fi
done

if [[ ${#failed[@]} -gt 0 ]]; then
    echo ""
    echo "docs-check FAILED for: ${failed[*]}"
    exit 1
fi

echo ""
echo "docs-check passed for all projects."
