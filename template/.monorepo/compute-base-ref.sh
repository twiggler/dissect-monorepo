#!/usr/bin/env bash
# Determines the base git ref to diff against for test-affected.
# Writes "ref=<sha>" to GITHUB_OUTPUT:
#   - pull_request event: the PR's base commit SHA
#   - regular push: the previous HEAD SHA (event.before)
#
# Expected environment variables (set via the step's env: block):
#   EVENT_NAME   — github.event_name
#   PR_BASE_SHA  — github.event.pull_request.base.sha
#   BEFORE_SHA   — github.event.before

set -euo pipefail

if [[ "$EVENT_NAME" == "pull_request" ]]; then
    ref="$PR_BASE_SHA"
else
    ref="$BEFORE_SHA"
fi

# Validate the ref exists locally (force-pushes can make before-SHA unreachable).
if [[ -n "$ref" ]] && ! git cat-file -e "${ref}^{commit}" 2>/dev/null; then
    echo "::warning::Base ref $ref not found in local history (force-push?). Falling back to HEAD^."
    ref="HEAD^"
fi

echo "ref=$ref" >> "$GITHUB_OUTPUT"
