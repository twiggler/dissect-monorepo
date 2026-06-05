#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
PROJECTS_FILE="$SCRIPT_DIR/project-list"

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "Error: $PROJECTS_FILE not found."
    exit 1
fi

echo "Deriving versions from namespaced git tags..."

while IFS= read -r line || [[ -n "$line" ]]; do
    # Clean the name to get just 'dissect.apfs'
    REPO_NAME=$(echo "$line" | sed 's/\*\]//g' | xargs | sed 's|github.com:fox-it/||')
    TOML_PATH="projects/$REPO_NAME/pyproject.toml"

    if [ ! -f "$TOML_PATH" ]; then
        echo "  [!] Skipping $REPO_NAME: pyproject.toml not found in projects/"
        continue
    fi

    echo "Processing $REPO_NAME..."

    # 1. Derive version from the namespaced git tags written by migrate.sh.
    # Tags have the form <repo>/<version> (e.g. dissect.apfs/1.2.3).
    CLEAN_VERSION=$(git tag --list "$REPO_NAME/*" | sort -V | tail -1 | sed "s|$REPO_NAME/||")

    if [ -z "$CLEAN_VERSION" ]; then
        echo "  [✗] No namespaced tag found for $REPO_NAME. Run migrate.sh first." >&2
        exit 1
    else
        echo "  [✓] $REPO_NAME is at version $CLEAN_VERSION"
    fi

    # 2. Modify the pyproject.toml
    # Remove dynamic/scm and inject the static version
    sed -i '/dynamic = \["version"\]/d' "$TOML_PATH"
    sed -i '/"setuptools-scm"/d' "$TOML_PATH"
    sed -i '/"setuptools_scm"/d' "$TOML_PATH"
    sed -i '/\[tool.setuptools_scm\]/,/^$/d' "$TOML_PATH"

    if grep -q "^version =" "$TOML_PATH"; then
        sed -i "s/^version = .*/version = \"$CLEAN_VERSION\"/" "$TOML_PATH"
    else
        sed -i "/\[project\]/a version = \"$CLEAN_VERSION\"" "$TOML_PATH"
    fi

done < "$PROJECTS_FILE"
