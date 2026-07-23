# dissect-monorepo-scripts

Scripts and configuration for building and maintaining the [dissect](https://github.com/fox-it/dissect) monorepo.

## Repository layout

```
template/                ← monorepo template (mirrors the target layout exactly)
  .github/workflows/     ← CI workflows deployed to the monorepo
  .monorepo/             ← operational scripts deployed to the monorepo
    tests/unit/          ← unit tests for the scripts in .monorepo/
    tests/integration/   ← integration tests for the monorepo tooling
    doc/                 ← design documentation
  .gitignore             ← monorepo-wide ignore rules (consolidates per-project .gitignore files)
  Justfile               ← task runner recipes (test, release, bump, …)
  pyproject.toml         ← workspace config and shared tool settings
  ruff.template.toml     ← linter/formatter config (renamed to ruff.toml on installation)
migrate/                 ← one-time migration pipeline (build monorepo from upstream)
  install_config.sh      ← copies template/ into a target monorepo checkout
  run_pipeline.sh        ← builds a fresh monorepo from the upstream sources
  migrate.sh             ← clones and merges each upstream project
  project-list           ← list of upstream repositories to migrate
  decouple_versions.sh   ← decouples pinned versions between projects
  internal_deps.py       ← wires up internal workspace dependencies
  centralize_deps.py     ← centralises shared dependencies
  centralize_ruff_config.py ← centralises ruff configuration
  update_project_src_layout.py ← normalises src layout across projects
```

`template/` is a verbatim mirror of what `migrate/install_config.sh` deploys to the target
monorepo root. A file at `template/.monorepo/affected_tests.py` lands at
`.monorepo/affected_tests.py` in the target. This 1-to-1 mapping means you edit
files in their deployed location — there is no separate "source vs. installed"
distinction within `template/`. The one exception is `ruff.template.toml`, which is
installed as `ruff.toml`.

## Quickstart

### Apply config changes to the monorepo

```sh
migrate/install_config.sh [TARGET_DIR]
```

Defaults to `../dissect-monorepo` if no target is given.

### Build a fresh monorepo from scratch

Requires `git`, `git-lfs`, `git-filter-repo`, and `uv` to be installed on the host.
To avoid installing these dependencies locally, use the [Docker or Podman workflow](#build-a-fresh-monorepo-using-docker-or-podman) instead.

```sh
migrate/run_pipeline.sh [TARGET_DIR]
```

### Build a fresh monorepo using Docker or Podman

A Dockerfile is provided to run the pipeline in an isolated environment, without needing to install the system dependencies locally.

**Build the image:**

```sh
docker build -t dissect-migration .
```

**Run the migration** — create the output directory first, then mount it to `/output`:

```sh
mkdir /tmp/dissect-monorepo-test
docker run --rm \
  -v /tmp/dissect-monorepo-test:/output \
  -e GIT_USER_NAME="$(git config user.name)" \
  -e GIT_USER_EMAIL="$(git config user.email)" \
  dissect-migration
```

**Using Podman** — the flags are identical, replace `docker` with `podman`:

```sh
podman build -t dissect-migration .

mkdir /tmp/dissect-monorepo-test
podman run --rm \
  -v /tmp/dissect-monorepo-test:/output:Z \
  -e GIT_USER_NAME="$(git config user.name)" \
  -e GIT_USER_EMAIL="$(git config user.email)" \
  dissect-migration
```

The `:Z` suffix relabels the directory for SELinux, which is required on Fedora/RHEL.

Using `/tmp` (typically tmpfs on Linux) keeps heavy git-history rewriting off the SSD. The
mounted directory must be empty.

> **Network access required.** The container clones ~30 repositories from GitHub and resolves
> packages from PyPI.

### Run the unit tests

```sh
uv run --group dev pytest template/.monorepo/tests/unit
```

### Run the integration tests locally

Point `MONOREPO_FIXTURE` at an already-built monorepo to skip the ~3-minute
`migrate/run_pipeline.sh` build step:

```sh
MONOREPO_FIXTURE=/tmp/dissect-monorepo-test uv run --group dev pytest template/.monorepo/tests/integration -v
```

Omit the variable to have pytest build a fresh monorepo automatically (slow, but
mirrors what CI does):

```sh
uv run --group dev pytest template/.monorepo/tests/integration -v
```

## Documentation

- [template/.monorepo/doc/recipes.md](template/.monorepo/doc/recipes.md) — Justfile recipe reference and user guide
- [template/.monorepo/doc/folder-layout.md](template/.monorepo/doc/folder-layout.md) — monorepo directory structure
- [template/.monorepo/doc/tooling.md](template/.monorepo/doc/tooling.md) — tooling choices and rationale
- [template/.monorepo/doc/release-strategy.md](template/.monorepo/doc/release-strategy.md) — release workflow
- [template/.monorepo/doc/testing-strategy.md](template/.monorepo/doc/testing-strategy.md) — testing approach

