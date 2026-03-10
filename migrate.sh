#!/bin/bash
set -e

# Configuration
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$SCRIPT_DIR/config"
PYPROJECTS_FILE="$CONFIG_DIR/pyproject.toml"
PROJECTS_FILE="$SCRIPT_DIR/project-list"
BASE_URL="git@github.com:fox-it"

# Initialize Monorepo
mkdir -p "projects"
cp "$PYPROJECTS_FILE" "pyproject.toml"
cp "$CONFIG_DIR/Justfile" "Justfile"

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
    git clone "$BASE_URL/$REPO_PATH.git" "$TEMP_CLONE"
    
    pushd "$TEMP_CLONE" > /dev/null
    git lfs fetch --all origin
    
    # Rewrite history into the projects/ folder
    # Also move a top-level `dissect/` directory (if present) into `src/dissect/`
    # so the monorepo layout becomes: projects/<repo>/src/dissect/...
    git filter-repo --to-subdirectory-filter "projects/$REPO_PATH" \
        --path-rename "projects/$REPO_PATH/dissect/:projects/$REPO_PATH/src/dissect/"
    
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

    # Internalize LFS objects by fetching them into the monorepo's LFS cache
    git lfs fetch origin_repo --all
    
    # Cleanup remote and temp files
    git remote remove origin_repo
    rm -rf "$TEMP_CLONE"

    # Unset any LFS URL that might have come from the individual repo
    git config --unset lfs.url || true

done < "$PROJECTS_FILE"

echo "Migration of all projects from $PROJECTS_FILE complete!"
