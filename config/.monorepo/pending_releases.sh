#!/usr/bin/env bash
# pending_releases.sh — list workspace packages whose current version has no release tag.
#
# A package is "pending" if no git tag of the form <name>/<version> exists for
# the version currently declared in its pyproject.toml. Tags are created by
# `just release` after a successful `uv publish`, so a missing tag means the
# version has not been published through the standard release workflow.
#
# Usage:
#   .monorepo/pending_releases.sh            # print a human-readable status table
#   .monorepo/pending_releases.sh --names    # print only the pending package names, one per line
#
# Exit code: 0 always (use --names output to drive further logic).

set -euo pipefail
trap 'exit 0' PIPE

# Populate two arrays by reference: pending and not_pending.
# Each element is "<name> <version>".
collect_releases() {
    local -n _pending=$1
    local -n _not_pending=$2

    for toml in projects/*/pyproject.toml; do
        [[ "$toml" == *"/template/"* ]] && continue

        name=$(grep -m1 '^name\s*=' "$toml" | sed 's/name\s*=\s*"\(.*\)"/\1/')
        version=$(grep -m1 '^version\s*=' "$toml" | sed 's/version\s*=\s*"\(.*\)"/\1/')

        if git tag --list "${name}/${version}" | grep -q .; then
            _not_pending+=("$name $version")
        else
            _pending+=("$name $version")
        fi
    done
}

print_names() {
    local -n _pending=$1
    for entry in "${_pending[@]+"${_pending[@]}"}"; do
        echo "${entry%% *}"
    done
}

print_table() {
    local -n _pending=$1
    local -n _not_pending=$2
    local col_width=30
    for entry in "${_pending[@]+"${_pending[@]}"}"; do
        printf "%-${col_width}s %-12s  no tag (pending)\n" "${entry%% *}" "${entry##* }"
    done
    for entry in "${_not_pending[@]+"${_not_pending[@]}"}"; do
        printf "%-${col_width}s %-12s  tagged\n" "${entry%% *}" "${entry##* }"
    done
}

pending=()
not_pending=()
collect_releases pending not_pending

if [[ "${1:-}" == "--names" ]]; then
    print_names pending
else
    print_table pending not_pending
fi
