# Plan: Dissect Monorepo — Release Strategy

### Background

All 31 `dissect.*` packages have been migrated from individual repositories into a single uv workspace monorepo. Each package remains an independently published PyPI artifact. The monorepo provides:

- A single place to develop and make cross-cutting changes
- Shared tooling: formatting (ruff), linting (vermin), testing (pytest-xdist), CI (GitHub Actions)
- Workspace-level dependency resolution during development — `[tool.uv.sources]` wires every `dissect.*` dependency to the local workspace copy, so published version bounds don't interfere with day-to-day work

---

### Decision 1: Version bumping stays manual

**Approach**: Developers bump the `version` field in a project's `pyproject.toml` directly, as they did before. No automation determines *what* the next version number should be.

**Rationale**: Tools like `python-semantic-release` or `commitizen` can be valuable — deriving version increments from commit message conventions (Conventional Commits: `feat:`, `fix:`, `chore:` etc.) reduces manual overhead and makes the release history machine-readable. However, adopting them would require migrating all contributors to a new commit discipline and adding tooling to every project. That is a worthwhile change to evaluate on its own terms, but it is independent of the monorepo migration and would add significant scope to it.

Introducing automated version bumping is therefore **out of scope for this migration**. The version decision remains manual, as it was before. What changes is the mechanics: in the per-repo workflow the version was dynamic, derived from a git tag at build time — pushing a tag *was* the release act. In the monorepo, tags no longer drive individual package releases, so the version is instead a static field in each project's `pyproject.toml`, edited directly before publishing.

---

### Decision 2: No automatic dependency constraint propagation — with one exception

**Approach**: When a developer adds a feature to `dissect.util` and wants to declare that downstream packages require at least that version, they update the lower bound manually in the affected `pyproject.toml` files. A `just set-constraint` recipe will make this a single command rather than a manual edit across N files.

**Exception**: The `dissect` meta-package is a pure aggregator with no source code — its sole purpose is to pull in all 31 `dissect.*` packages. Because it carries no logic of its own, its dependency constraints have no semantic meaning beyond "point at what's current". Its constraints will therefore be **calculated automatically**: a script reads the `version` field from each workspace member's `pyproject.toml` and generates pinned lower bounds of the form `dissect.util>=3.24,<4` for each entry. This script runs as part of the release workflow, just before building and publishing the meta-package.

**Rationale**: Analysis of all internal `dissect.*` dependencies across the 31 projects shows that the vast majority use **loose major-version lower bounds** (`>=3,<4`, `>=4,<5`, etc.). Under this scheme, any minor release is automatically compatible with all downstream consumers — no propagation is needed. Propagation is only relevant when a developer intentionally tightens a lower bound to mandate a new minimum minor version, which is a deliberate, infrequent decision. When that decision is made, `just set-constraint` makes the mechanical part a single command — it updates the specifier across every `pyproject.toml` that already declares the dependency — so the developer can focus on the intent rather than hunting down files.

**Tight lower bounds currently in use**

| Package | Constraint |
|---|---|
| `dissect.apfs` | `dissect.fve>=4.2`, `dissect.util>=3.23` |
| `dissect.archive` | `dissect.util>=3.22` |
| `dissect.btrfs` | `dissect.util>=3.23` |
| `dissect.database` | `dissect.util>=3.24` |
| `dissect.etl` | `dissect.cstruct>=4.6` |
| `dissect.executable` | `dissect.cstruct>=4.6` |
| `dissect.fve` | `dissect.util>=3.22` |
| `dissect.target` | `dissect.database>=1.1`, `dissect.evidence>=3.13`, `dissect.hypervisor>=3.21`, `dissect.ntfs>=3.16`, `dissect.regf>=3.13`, `dissect.volume>=3.17`, `dissect.apfs>=1.1`, `dissect.fve>=4.5`, `dissect.jffs>=1.5`, `dissect.qnxfs>=1.1`, `dissect.vmfs>=3.12` |

Everything else — 23 of 31 packages for most of their dependencies — uses loose major-version bounds.

---

### Decision 3: Release detection via PyPI version comparison

**Problem**: In the old per-repo workflow, pushing a git tag immediately triggered a release pipeline. In the monorepo, version bumps are commits and there is no per-package tag-triggered release. We need a way to determine which packages have unpublished local versions before running `uv publish`.

**Approach**: A `pending-releases.py` script queries the PyPI JSON API for each of the 31 packages, retrieves the latest published version, and compares it to the `version` field in the local `pyproject.toml`. Any package where the local version is not yet on PyPI is reported as pending.

```
$ python pending-releases.py
dissect.util        3.24.1  →  not on PyPI (pending)
dissect.database    3.24.0  →  already published
...
```

A corresponding `just release` recipe would: (1) run `pending-releases.py` to enumerate what needs publishing, (2) build and publish each pending package via `uv publish`, (3) create a namespaced git tag `dissect.util/3.24.1` for each published package. The tags provide a permanent release record and enable future changelog generation via `git log dissect.util/3.24.1..HEAD -- projects/dissect.util/`.

The recipe accepts an optional space-separated list of package names to restrict the release to a subset:

```
just release dissect.util dissect.cstruct
```

When no packages are specified, all pending packages are released.

The GitHub Actions `workflow_dispatch` trigger supports typed form inputs, which GitHub renders as a proper form in the UI when manually triggering a workflow. A `string` input is used to pass the optional package list:

```yaml
on:
  workflow_dispatch:
    inputs:
      packages:
        description: 'Space-separated list of packages to release (leave empty for all pending)'
        required: false
        default: ''
        type: string
```

The workflow then forwards the value directly to the recipe:

```yaml
- run: just release ${{ inputs.packages }}
```

Leaving the field blank in the UI releases everything pending; filling it in restricts the run to the named packages.

**Alternatives considered**:
- *Upload all, skip existing* (`uv publish --skip-existing`): simpler to operate but builds all 31 packages every time, even when nothing changed.
- *Per-package git tags only*: avoids the PyPI query but requires tag discipline and fails silently if a tag is forgotten.

---

### Remaining Work

#### 1. `dissect` meta-package

The bare `dissect` package (no suffix) does not currently exist in the monorepo.

#### 2. `pending-releases.py` script

A Python script (to be placed in `.monorepo/` so it is available inside the monorepo) that:

1. Reads all workspace members from `pyproject.toml`
2. For each member, reads the local `version` from its `pyproject.toml`
3. Queries `https://pypi.org/pypi/{name}/json`
4. Reports packages where the local version has no matching entry in `releases` on PyPI

This is a read-only, side-effect-free pre-flight check. It can also be used standalone for visibility without triggering any publish.

#### 3. `just set-constraint` recipe

A recipe that accepts a package name and a new version specifier, then updates every `projects/*/pyproject.toml` that already declares a dependency on that package — across `[project.dependencies]` and all `[project.optional-dependencies]` groups. It uses `tomlkit` for lossless round-tripping (preserving comments, formatting, and ordering).

```
just set-constraint dissect.cstruct ">=4.7,<5"
```

Only projects that already list the dependency are modified; the recipe will not add new dependencies.

