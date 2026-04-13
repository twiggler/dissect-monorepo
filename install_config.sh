#!/usr/bin/env bash
set -euo pipefail

# Copies (or refreshes) the monorepo-level config files into a target directory.
# Run this after modifying anything under config/ (Justfile, pyproject.toml,
# ruff.toml, .github/**, .monorepo/**) without having to redo the full migration.
#
# Usage: ./install_config.sh [TARGET_DIR]
#   TARGET_DIR  Monorepo root to install into.
#               Defaults to a sibling directory named 'dissect-monorepo'.

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$SCRIPT_DIR/config"
TARGET_DIR=$(realpath -m "${1:-$SCRIPT_DIR/../dissect-monorepo}")

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Error: TARGET_DIR ($TARGET_DIR) does not exist." >&2
  exit 1
fi

echo "Installing config into: $TARGET_DIR"

mkdir -p "$TARGET_DIR/projects"
cp "$CONFIG_DIR/pyproject.toml" "$TARGET_DIR/pyproject.toml"
cp "$CONFIG_DIR/ruff.toml"      "$TARGET_DIR/ruff.toml"
cp "$CONFIG_DIR/Justfile"       "$TARGET_DIR/Justfile"
cp "$CONFIG_DIR/.gitignore"     "$TARGET_DIR/.gitignore"
rm -rf "$TARGET_DIR/.github" "$TARGET_DIR/.monorepo" "$TARGET_DIR/doc"
rsync -r --exclude='__pycache__' "$CONFIG_DIR/.github/"   "$TARGET_DIR/.github/"
rsync -r --exclude='__pycache__' "$CONFIG_DIR/.monorepo/" "$TARGET_DIR/.monorepo/"
rsync -r --exclude='__pycache__' "$SCRIPT_DIR/doc/"       "$TARGET_DIR/doc/"

echo "Done."
