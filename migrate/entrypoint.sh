#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)

GIT_USER_EMAIL="${GIT_USER_EMAIL:-migration@docker}"
GIT_USER_NAME="${GIT_USER_NAME:-Docker Migration}"

git config --global user.email "$GIT_USER_EMAIL"
git config --global user.name "$GIT_USER_NAME"

exec bash "$SCRIPT_DIR/run_pipeline.sh" /output
