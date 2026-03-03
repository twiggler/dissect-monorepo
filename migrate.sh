#!/bin/bash
set -e

# Configuration
PROJECTS_FILE="project-list"
BASE_URL="git@github.com:fox-it"

# Check if projects file exists (looking in current dir or one level up)
if [ ! -f "$PROJECTS_FILE" ]; then
    if [ -f "../$PROJECTS_FILE" ]; then
        PROJECTS_FILE="../$PROJECTS_FILE"
    else
        echo "Error: $PROJECTS_FILE not found in current or parent directory."
        exit 1
    fi
fi

# Safety check: Ensure we are in a git repo and have a projects folder
if [ ! -d ".git" ]; then
    echo "Error: You must run this script from the root of your git repository."
    exit 1
fi

mkdir -p "projects"

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
    
    # Rewrite history into the projects/ folder
    git filter-repo --to-subdirectory-filter "projects/$REPO_PATH"
    
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
    
    # Cleanup remote and temp files
    git remote remove origin_repo
    rm -rf "$TEMP_CLONE"

done < "$PROJECTS_FILE"

# 2. Re-sync the uv Workspace
echo "----------------------------------------------------"
echo "Updating uv lockfile..."
uv lock

echo "Migration of all projects from $PROJECTS_FILE complete!"
