#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
PROJECTS_FILE="$SCRIPT_DIR/project-list"
BASE_API="https://api.github.com/repos/fox-it"

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "Error: $PROJECTS_FILE not found."
    exit 1
fi

echo "Fetching authoritative versions from GitHub API..."

while IFS= read -r line || [[ -n "$line" ]]; do
    # Clean the name to get just 'dissect.apfs'
    REPO_NAME=$(echo "$line" | sed 's/\*\]//g' | xargs | sed 's|github.com:fox-it/||')
    TOML_PATH="projects/$REPO_NAME/pyproject.toml"

    if [ ! -f "$TOML_PATH" ]; then
        echo "  [!] Skipping $REPO_NAME: pyproject.toml not found in projects/"
        continue
    fi

    echo "Processing $REPO_NAME..."

    # 1. Fetch the latest tag name from GitHub
    # --silent: no progress/error output, --fail: exit non-zero on HTTP error (4xx/5xx)
    if ! TAGS_JSON=$(curl --silent --fail "$BASE_API/$REPO_NAME/tags"); then
        echo "  [✗] Failed to fetch tags for $REPO_NAME from GitHub API (network or HTTP error)." >&2
        exit 1
    fi
    LATEST_TAG=$(echo "$TAGS_JSON" | grep --max-count=1 '"name":' | cut --delimiter='"' --fields=4) || true  # grep exits 1 on no match; handled below

    # 2. Clean the version (e.g., 'v1.2.3' -> '1.2.3')
    CLEAN_VERSION=$(echo "$LATEST_TAG" | sed 's/.*v//;s/[^0-9.]*//g')

    if [ -z "$CLEAN_VERSION" ]; then
        echo "  [✗] No tag found on GitHub for $REPO_NAME. Cannot determine version." >&2
        exit 1
    else
        echo "  [✓] GitHub says $REPO_NAME is at version $CLEAN_VERSION"
    fi

    # 3. Modify the pyproject.toml
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
