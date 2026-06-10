#!/bin/bash
set -e

# Configuration
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
PROJECTS_FILE="$SCRIPT_DIR/project-list"
BASE_URL="https://github.com/fox-it"

# Initialize Monorepo
bash "$SCRIPT_DIR/install_config.sh" "$(pwd)"

# 1. Read and Process Repositories
while IFS= read -r line || [[ -n "$line" ]]; do
    # Clean the line: remove metadata and domain prefix
    # Converts 'github.com:fox-it/dissect.apfs' to 'dissect.apfs'
    REPO_PATH=$(echo "$line" | sed 's/\*\]//g' | xargs | sed 's|github.com:fox-it/||')
    
    if [ -z "$REPO_PATH" ]; then continue; fi

    echo "----------------------------------------------------"
    echo "Migrating: $REPO_PATH"
    echo "----------------------------------------------------"

    # Define temp clone path
    TEMP_CLONE="/tmp/migrate_$REPO_PATH"
    rm -rf "$TEMP_CLONE"

    # Clone the individual repo
    git clone "$BASE_URL/$REPO_PATH" "$TEMP_CLONE"
    
    pushd "$TEMP_CLONE" > /dev/null
    git lfs fetch --all origin

    # Rewrite bare '#N' PR/issue references to qualified cross-repository links
    # ('fox-it/<repo>#N') so they remain navigable in the monorepo.
    # GitHub renders 'owner/repo#N' as a clickable cross-repository link:
    # https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/autolinked-references-and-urls#issues-and-pull-requests
    COMMIT_CALLBACK="
import re
commit.message = re.sub(rb'(?<!\w)#(\d+)', rb'fox-it/$REPO_PATH#\1', commit.message)
"
    # Namespace all tags as <repo>/<version> (e.g. v1.2.3 -> dissect.apfs/1.2.3).
    # The leading 'v' is stripped only when followed by a digit, so non-version
    # tags like 'validate-fix' become 'dissect.apfs/validate-fix' unchanged.
    REFNAME_CALLBACK="
import re
if refname.startswith(b'refs/tags/'):
    tag = refname[len(b'refs/tags/'):]
    tag = re.sub(rb'^v(?=\d)', b'', tag)
    return b'refs/tags/$REPO_PATH/' + tag
return refname
"

    # Rewrite history into the projects/ folder.
    # Also move a top-level `dissect/` directory (if present) into `src/dissect/`
    # so the monorepo layout becomes: projects/<repo>/src/dissect/...
    # tox.ini and .gitignore are excluded: tox is superseded by `just` recipes in the monorepo,
    # and .gitignore is consolidated into the monorepo root .gitignore.
    # tests/_docs/Makefile is excluded: the monorepo calls sphinx-build directly via
    # 'just docs-check', so the per-project Makefile is no longer needed.
    git filter-repo --to-subdirectory-filter "projects/$REPO_PATH" \
        --path-rename "projects/$REPO_PATH/dissect/:projects/$REPO_PATH/src/dissect/" \
        --invert-paths \
        --path "projects/$REPO_PATH/tox.ini" \
        --path "projects/$REPO_PATH/.github" \
        --path "projects/$REPO_PATH/.gitignore" \
        --path "projects/$REPO_PATH/tests/_docs/Makefile" \
        --commit-callback "$COMMIT_CALLBACK" \
        --refname-callback "$REFNAME_CALLBACK"

    # Save the commit-map before leaving the temp clone.
    # It maps every old SHA (from the original repo) to the new SHA assigned
    # by filter-repo, and is used below to translate .git-blame-ignore-revs.
    cp .git/filter-repo/commit-map "/tmp/commit-map-$REPO_PATH"

    popd > /dev/null

    # Merge into the existing Monorepo
    git remote add origin_repo "$TEMP_CLONE"
    git fetch origin_repo
    
    # Detect default branch (main or master)
    BRANCH="main"
    if ! git rev-parse --verify "origin_repo/main" >/dev/null 2>&1; then
        BRANCH="master"
    fi

    # Perform the merge with history preservation
    git merge "origin_repo/$BRANCH" --allow-unrelated-histories -m "Merge $REPO_PATH into monorepo"
    # Mark the merge commit so bump_version can find pre-migration work for this project.
    git tag "migration/start/$REPO_PATH"

    # Internalize LFS objects by fetching them into the monorepo's LFS cache
    git lfs fetch origin_repo --all

    # Translate and aggregate .git-blame-ignore-revs into the monorepo root.
    # filter-repo rewrites every commit SHA, so the per-project file's hashes
    # must be mapped to their new values before they are useful.
    uv run --no-project "$SCRIPT_DIR/update_blame_ignore_revs.py" "$REPO_PATH" "/tmp/commit-map-$REPO_PATH"
    rm -f "/tmp/commit-map-$REPO_PATH"

    # Cleanup remote and temp files
    git remote remove origin_repo
    rm -rf "$TEMP_CLONE"

    # Unset any LFS URL that might have come from the individual repo
    git config --unset lfs.url || true

done < "$PROJECTS_FILE"

echo "Migration of all projects from $PROJECTS_FILE complete!"
