# Justfile for running tests across the monorepo
# Usage:
#   just test-all
#   just test <project> <env>
#   just test-affected
#   just test-affected origin/master 3.11


# Update the version specifier for an internal dependency across all projects.
# Only modifies projects that already declare the dependency.
# Example: just set-constraint dissect.cstruct ">=4.7,<5"
set-constraint package specifier:
    uv run .monorepo/set_constraint.py '{{package}}' '{{specifier}}'

# Run ruff check+format over all projects.
# Pass fix="true" to auto-fix instead of reporting.
ruff fix="false":
    uv run --group dev ruff check {{ if fix == "true" { "--fix" } else { "" } }}
    uv run --group dev ruff format {{ if fix == "true" { "" } else { "--check" } }}

# Internal: run vermin minimum-version check over all projects.
# `typing_extensions` is excluded because vermin reports it as requiring ~2/~3
# (the module's own declared compatibility range), which is a false positive
# unrelated to the actual code under analysis.
# See: https://github.com/netromdk/vermin/issues/330
vermin:
    uv run --group dev vermin -t=3.10- --no-tips --lint --exclude typing_extensions projects

# Check formatting and linting (ruff + vermin).
lint:
    just ruff
    just vermin

# Auto-fix ruff issues (vermin has no auto-fix).
fix:
    just ruff true

# Run pytest for a single project using `uv` to create the environment.
# --all-packages installs all workspace members as editable so sibling deps are importable.
# --all-extras ensures optional dependencies (e.g. backports.zstd) are available.
# Example: just test dissect.xfs 3.11
# Example: just test dissect.xfs 3.11 "-k test_foo"
test project env args="":
    #!/usr/bin/env bash
    set -uo pipefail
    uv run --group dev --all-packages --all-extras --python {{env}} \
        pytest -n auto projects/{{project}} {{args}} \
        || exit_code=$?
    # Exit code 5 means no tests were collected — not a failure.
    [ "${exit_code:-0}" -eq 5 ] || exit "${exit_code:-0}"

# Run pytest for every project using the given Python version.
# Skips directories that don't have a pyproject.toml.
test-all env="3.10":
    #!/usr/bin/env bash
    set -euo pipefail
    for d in projects/*; do
        if [ -f "$d/pyproject.toml" ]; then
            project_name=$(basename "$d")
            echo "--- Running tests for $project_name with Python {{env}} ---"
            just test "$project_name" {{env}}
        fi
    done

# Run pytest for every project across all configured Python environments.
# Reads python-versions from [tool.monorepo.test] in pyproject.toml.
test-all-envs:
    #!/usr/bin/env bash
    set -euo pipefail
    mapfile -t envs < <(uv run .monorepo/matrix.py --format versions)
    for env in "${envs[@]}"; do
        echo "=== Testing with Python $env ==="
        just test-all "$env"
    done

# Run tests only for packages affected by changes vs a base ref.
# Example: just test-affected origin/master 3.11
test-affected ref="origin/master" env="3.10":
    #!/usr/bin/env bash
    set -euo pipefail
    packages=$(git diff --name-only {{ref}} | uv run .monorepo/affected_tests.py)
    if [ -z "$packages" ]; then
        echo "No packages affected. Nothing to do."
        exit 0
    fi
    echo "Affected packages: $packages"
    for pkg in $packages; do
        just test "$pkg" {{env}}
    done
