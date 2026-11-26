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
  README.md              ← monorepo landing page (project overview and table)
  Justfile               ← task runner recipes (test, release, bump, …)
  pyproject.toml         ← workspace config and shared tool settings
  ruff.template.toml     ← linter/formatter config (renamed to ruff.toml on installation)
migrate/                 ← one-time migration pipeline (build monorepo from upstream)
  install_config.sh      ← copies template/ into a target monorepo checkout
  run_pipeline.sh        ← builds a fresh monorepo from the upstream sources
  overwrite_remote.sh    ← replaces a GitHub repo's branches, tags and PRs with a local build
  migrate.sh             ← clones and merges each upstream project
  project-list           ← list of upstream repositories to migrate
  decouple_versions.sh   ← decouples pinned versions between projects
  internal_deps.py       ← wires up internal workspace dependencies
  centralize_deps.py     ← centralises shared dependencies
  centralize_ruff_config.py ← centralises ruff configuration
  update_project_src_layout.py ← normalises src layout across projects
utils/                   ← one-off tools (migrate_pr.py moves legacy PRs to the monorepo)
comms/                   ← migration announcements and the script that posts them
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

### Overwrite a GitHub repository with a fresh build

```sh
migrate/overwrite_remote.sh /tmp/dissect-monorepo-test twiggler/dissect-monorepo-test
```

**Destructive.** This force-pushes `main` and replaces all remote tags with the local ones.
It makes `main` the default branch, closes all open PRs, and deletes every other branch.
It prints what will change and asks you to type the repository name to confirm. Pass
`--yes` to skip the prompt. LFS objects are uploaded by the git-lfs `pre-push` hook as part
of the push. Requires an authenticated `gh` CLI.

#### Nightly refresh of the test monorepo

[`.github/workflows/refresh-test-monorepo.yml`](.github/workflows/refresh-test-monorepo.yml)
rebuilds the monorepo every night at 22:41 UTC and runs `overwrite_remote.sh` against
`twiggler/dissect-monorepo-test`. The push triggers the test repo's CI on the fresh build. The
test repo's own nightly CI (02:00 UTC) normally picks it up too. To run it by hand:

```sh
gh workflow run refresh-test-monorepo.yml
```

It pushes as a dedicated GitHub App that is installed only on `dissect-monorepo-test`, with
Contents, Workflows and Pull requests write access. Each run mints a 1-hour token after the
build has finished. The app's client ID (variable `TEST_MONOREPO_APP_CLIENT_ID`) and private
key (secret `TEST_MONOREPO_APP_PRIVATE_KEY`) live in this repo's `test-monorepo` environment,
which only `master` can use.

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

