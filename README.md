# dissect-monorepo-scripts

Scripts and configuration for building and maintaining the [dissect](https://github.com/fox-it/dissect) monorepo.

## Repository layout

```
config/                  ← monorepo template (mirrors the target layout exactly)
  .github/workflows/     ← CI workflows deployed to the monorepo
  .monorepo/             ← operational scripts deployed to the monorepo
  Justfile               ← task runner recipes (test, release, bump, …)
  pyproject.toml         ← workspace config and shared tool settings
  ruff.toml              ← linter/formatter config
doc/                     ← design documentation
migrate/                 ← one-time migration pipeline (build monorepo from upstream)
  install_config.sh      ← copies config/ into a target monorepo checkout
  run_pipeline.sh        ← builds a fresh monorepo from the upstream sources
  migrate.sh             ← clones and merges each upstream project
  project-list           ← list of upstream repositories to migrate
  decouple_versions.sh   ← decouples pinned versions between projects
  internal_deps.py       ← wires up internal workspace dependencies
  centralize_deps.py     ← centralises shared dependencies
  centralize_ruff_config.py ← centralises ruff configuration
  update_project_src_layout.py ← normalises src layout across projects
tests/unit/              ← unit tests for the scripts in config/.monorepo/
```

`config/` is a verbatim mirror of what `migrate/install_config.sh` deploys to the target
monorepo root. A file at `config/.monorepo/affected_tests.py` lands at
`.monorepo/affected_tests.py` in the target. This 1-to-1 mapping means you edit
files in their deployed location — there is no separate "source vs. installed"
distinction within `config/`.

## Quickstart

### Apply config changes to the monorepo

```sh
migrate/install_config.sh [TARGET_DIR]
```

Defaults to `../dissect-monorepo` if no target is given.

### Build a fresh monorepo from scratch

```sh
migrate/run_pipeline.sh [TARGET_DIR]
```

### Run the unit tests

```sh
uv run --group dev pytest tests/unit
```

### Run the integration tests locally

Point `MONOREPO_FIXTURE` at an already-built monorepo to skip the ~3-minute
`migrate/run_pipeline.sh` build step:

```sh
MONOREPO_FIXTURE=/tmp/dissect-monorepo-test uv run --group dev pytest tests/integration -v
```

Omit the variable to have pytest build a fresh monorepo automatically (slow, but
mirrors what CI does):

```sh
uv run --group dev pytest tests/integration -v
```

## Documentation

- [doc/recipes.md](doc/recipes.md) — Justfile recipe reference and user guide
- [doc/folder-layout.md](doc/folder-layout.md) — monorepo directory structure
- [doc/tooling.md](doc/tooling.md) — tooling choices and rationale
- [doc/release-strategy.md](doc/release-strategy.md) — release workflow
- [doc/testing-strategy.md](doc/testing-strategy.md) — testing approach

