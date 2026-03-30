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

**Why tags do not trigger releases in the monorepo**: restoring the tag-as-trigger model would require CI to write the version back into `pyproject.toml` (and regenerate `uv.lock`) and push that commit to `master`. This creates several compounding problems: CI needs write access and the push must bypass branch protection rules; the machine-generated commit appears in `git log` and `git blame`; pushing 10 release tags simultaneously fires 10 independent concurrent workflows with no coordination between them; and any failure mid-way leaves `pyproject.toml` out of sync with the published state. The `workflow_dispatch` trigger avoids all of this — it provides the same explicit "I am intentionally releasing now" signal, while leaving version management in the developer's hands and keeping CI read-only with respect to the repository.

`just bump-minor` and `just bump-patch` recipes will handle the mechanical part — they increment the `version` field in the `pyproject.toml` of one or more projects and are usable for both single and bulk bumps:

```
just bump-minor dissect.util dissect.cstruct   # bump specific packages
just bump-minor                                 # bump all workspace members
just bump-patch dissect.util                    # patch bump a single package
```

Both recipes run `uv lock` after editing `pyproject.toml` files so the workspace lockfile stays consistent.

**Preventing double-bumps**: a developer who bumps a version but does not immediately publish creates an invisible pending state — a second developer (or the same one, later) may bump again without realising the first bump has not been released yet. Both `bump-minor` and `bump-patch` enforce this guard by **reusing the same pending-releases check** used by `just release`: before making any changes, they call into the pending-releases logic to determine whether the current local version of each target package already has a corresponding release tag. If no tag exists, the version has never been released and the recipe aborts with an error. The developer is prompted to either release the pending version first or explicitly bundle the new work under it. Version bumps should only be committed together with the feature or fix that motivates them, not as speculative pre-bumps.

---

### Decision 2: No automatic dependency constraint propagation — with one exception

**Approach**: When a developer adds a feature to `dissect.util` and wants to declare that downstream packages require at least that version, they update the lower bound manually in the affected `pyproject.toml` files. A `just set-constraint` recipe will make this a single command rather than a manual edit across N files.

**Exception**: The `dissect` meta-package is a pure aggregator with no source code — its sole purpose is to pull in all 31 `dissect.*` packages. Because it carries no logic of its own, its dependency constraints have no semantic meaning beyond "point at what's current". Its constraints will therefore be **calculated automatically**: a script reads the `version` field from each workspace member's `pyproject.toml` and generates pinned lower bounds of the form `dissect.util>=3.24,<4` for each entry. This script runs as part of the release workflow, just before building and publishing the meta-package.

**Rationale**: Analysis of all internal `dissect.*` dependencies across the 31 projects shows that the vast majority use **loose major-version lower bounds** (`>=3,<4`, `>=4,<5`, etc.). Under this scheme, any minor release is automatically compatible with all downstream consumers — no propagation is needed. Propagation is only relevant when a developer intentionally tightens a lower bound to mandate a new minimum minor version, which is a deliberate, infrequent decision. When that decision is made, `just set-constraint` makes the mechanical part a single command — it updates the specifier across every `pyproject.toml` that already declares the dependency — so the developer can focus on the intent rather than hunting down files. The recipe runs `uv lock` afterward to keep the workspace lockfile consistent with the updated constraints.

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

### Decision 3: Release detection via git tags

**Problem**: In the old per-repo workflow, pushing a git tag immediately triggered a release pipeline. In the monorepo, version bumps are commits and there is no per-package tag-triggered release. We need a way to determine which packages have unpublished local versions before running `uv publish`.

**Approach**: A `pending-releases.py` script determines pending packages by comparing each workspace member's local `version` field to the set of existing git tags. A package is pending if no tag of the form `<name>/<version>` exists for its current local version. This check is fully offline and instant.

```
$ python pending-releases.py
dissect.util        3.24.1  →  no tag (pending)
dissect.database    3.24.0  →  tagged (published)
...
```

A corresponding `just release` recipe would: (1) run `pending-releases.py` to enumerate what needs publishing, (2) build and publish each pending package via `uv publish`, (3) create a namespaced git tag `dissect.util/3.24.1` for each successfully published package. The tags provide a permanent release record and enable future changelog generation via `git log dissect.util/3.24.1..HEAD -- projects/dissect.util/`.

**Non-authoritative by design**: the tag-based check assumes that `just release` is the only publication path. If a package is published manually without going through the recipe (and thus without creating a tag), it will appear pending again and `uv publish` will return a 409 conflict — a visible, recoverable error. The fix is to create the missing tag manually. This is acceptable because manual out-of-band publishing is not part of normal workflow.

This same logic is reused by `just bump-minor` and `just bump-patch` as the double-bump guard (see Decision 1).

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
- *PyPI JSON API query*: authoritative — reflects actual published state regardless of tag discipline — but requires a network call for all 31 packages on every run. Retained as a fallback option if the tag-based approach causes false positives in practice.

---

### Decision 4: GitHub Actions release workflow and authentication

**Workflow**: `config/.github/workflows/release.yml` (applied to the monorepo via `install_config.sh`) exposes `just release` as a manually triggered GitHub Actions workflow. It accepts two inputs rendered as form fields in the GitHub UI:

| Input | Default | Description |
|---|---|---|
| `packages` | `all` | Space-separated package names, or `all` for every pending package |
| `index` | `pypi` | Target index: `pypi` or `testpypi` |

A concurrency group (`group: release`, `cancel-in-progress: false`) ensures that at most one release workflow runs at a time and that an in-progress release is never cancelled by a concurrent trigger.

The `index` input maps directly to a **GitHub environment** of the same name (`pypi` or `testpypi`). Environments serve two purposes here: they act as deployment gates (the `pypi` environment can be configured to require a manual review before proceeding) and they scope secrets — `UV_PUBLISH_TOKEN` is stored per-environment so that the testpypi token cannot accidentally be used to publish to pypi and vice versa.

**Authentication strategy — dual-mode**

The workflow supports two authentication modes and automatically selects between them at runtime:

1. **Account-scoped API token** (primary): If a secret named `UV_PUBLISH_TOKEN` is stored in the active GitHub environment, `uv publish` uses it directly. A single account-scoped token covers all 31 packages, so one token per index (pypi, testpypi) is sufficient.

2. **OIDC Trusted Publishing** (fallback): If no `UV_PUBLISH_TOKEN` secret is present in the environment, the workflow falls back to PyPI's [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) mechanism. The workflow is granted the `id-token: write` permission, which allows it to obtain a short-lived, cryptographically verifiable OIDC token from GitHub that PyPI accepts in place of a long-lived credential.

The guard that implements this:

```yaml
env:
  UV_PUBLISH_TOKEN: ${{ secrets.UV_PUBLISH_TOKEN || '' }}
run: |
  if [[ -z "$UV_PUBLISH_TOKEN" ]]; then unset UV_PUBLISH_TOKEN; fi
  just release $PACKAGES --index $INDEX
```

GitHub resolves an unset or empty secret to an empty string `""`. The explicit `unset` ensures that `uv` never receives an empty token — an empty string would cause an authentication error rather than triggering the OIDC fallback.

**Why account-scoped tokens instead of per-package Trusted Publishers**

PyPI Trusted Publisher setup requires clicking through a per-package form on pypi.org (one submission per package per index). With 31 packages and two indexes (pypi + testpypi) that is 62 one-time manual setup operations. PyPI provides no public API for this; it cannot be automated. An account-scoped API token is a single credential that covers all packages under the account, reducing the setup to one token per index regardless of how many packages exist.

OIDC Trusted Publishing remains available as a zero-credential fallback: once a Trusted Publisher is configured for a given package (if ever), the workflow will automatically use it when no `UV_PUBLISH_TOKEN` secret is set in the environment.

**Pending user actions — environment and secret setup**

Create both GitHub environments and add secrets via the repository Settings → Environments UI, or via `gh api`:

```bash
# Create environments
gh api repos/OWNER/REPO/environments/pypi -X PUT
gh api repos/OWNER/REPO/environments/testpypi -X PUT
```

Then for each environment, add a `UV_PUBLISH_TOKEN` secret containing an account-scoped API token created at pypi.org / test.pypi.org → Account Settings → API tokens. Optionally add Required Reviewers to the `pypi` environment for a manual approval gate before production releases.

---

### Remaining Work

#### Done

- **`release.sh`**: builds pending packages via `uv build`, publishes via `uv publish`, and pushes namespaced git tags. Package name validation (`^[a-zA-Z0-9._-]+$`) and safe directory cleanup (`find -mindepth 1 -delete`) are in place.
- **`pending_releases.sh`**: offline tag-based check used by `release.sh` to enumerate pending packages.
- **`just release` recipe**: exposes `release.sh` as a `just` recipe in `Justfile`.
- **`[[tool.uv.index]]` entries**: `pypi` and `testpypi` index entries (including `publish-url`) are present in the root `pyproject.toml`.
- **`release.yml` GitHub Actions workflow**: `workflow_dispatch` workflow with `packages` and `index` inputs, GitHub environment gating, and dual-auth (API token + OIDC fallback).

#### Pending user actions

- Create `pypi` and `testpypi` GitHub environments in repository Settings → Environments (see Decision 4).
- Add `UV_PUBLISH_TOKEN` secret to each environment (account-scoped API token from pypi.org / test.pypi.org).
- Optionally add Required Reviewers to the `pypi` environment for a manual approval gate.

#### 1. `just bump-minor` and `just bump-patch` recipes

Two recipes that accept an optional list of package names and increment the `version` field in each matching `projects/*/pyproject.toml`. `bump-minor` increments the minor component and resets patch to `0` (e.g. `3.24.1 → 3.25.0`); `bump-patch` increments only the patch component (e.g. `3.24.0 → 3.24.1`). When no packages are specified, all workspace members are bumped.

```
just bump-minor dissect.util dissect.cstruct
just bump-patch dissect.util
just bump-minor
```

Before making any changes, both recipes call the **pending-releases check** (the same logic used by `just release`) to verify that the current local version of each target package has a corresponding release tag. If no such tag exists, that version has never been released and the recipe aborts — enforcing the double-bump guard locally and offline. After editing `pyproject.toml` files, both recipes run `uv lock` to keep the workspace lockfile up to date.

#### 2. `dissect` meta-package

The bare `dissect` package (no suffix) does not currently exist in the monorepo.

#### 3. `pending-releases.py` script

A script (to be placed in `.monorepo/`) that:

1. Reads all workspace members from the root `pyproject.toml`
2. For each member, reads the local `version` from its `pyproject.toml`
3. Checks whether a git tag `<name>/<version>` exists
4. Reports packages where no such tag exists as pending

This check is fully offline and side-effect-free. It is used by both `just release` (to enumerate what to publish) and `just bump-minor`/`just bump-patch` (as the double-bump guard), so the logic lives in one place.

#### 4. `just set-constraint` recipe

A recipe that accepts a package name and a new version specifier, then updates every `projects/*/pyproject.toml` that already declares a dependency on that package — across `[project.dependencies]` and all `[project.optional-dependencies]` groups. It uses `tomlkit` for lossless round-tripping (preserving comments, formatting, and ordering).

```
just set-constraint dissect.cstruct ">=4.7,<5"
```

Only projects that already list the dependency are modified; the recipe will not add new dependencies.

---

### Known Risk: Ghost Dependencies and the Workspace Masking Problem

**The problem**: A ghost dependency (sometimes called a phantom dependency) is an undeclared package that a project uses at runtime but does not list in `[project.dependencies]`. The package happens to be installed in the environment because something *else* pulled it in transitively. The code works, tests pass, but the published package is broken for any user whose environment doesn't include that transitive package — because there is no constraint to guarantee it will be present.

This is not a new problem, but the monorepo workspace makes it systematically harder to detect.

**How `[tool.uv.sources]` masks it**: When running tests inside the monorepo, `uv sync --all-packages` installs every workspace member into a single shared environment. This means `dissect.target`'s test environment contains `dissect.util`, `dissect.cstruct`, `dissect.ntfs`, and every other workspace member — regardless of whether `dissect.target` actually declares a dependency on them. A developer could accidentally import `dissect.ntfs` directly from `dissect.target` code, never declare it as a dependency, and all tests would pass locally and in CI. The bug only surfaces when an external user installs `dissect.target` from PyPI into a fresh environment that doesn't happen to have `dissect.ntfs`.

The same masking applies to version constraints. If `dissect.target` declares `dissect.util>=3.0` but actually uses an API introduced in `3.24`, tests always pass in the workspace because the workspace always resolves to the current local version of `dissect.util`. An external user pinned to `dissect.util==3.0` would get an `AttributeError`.

**The solution: per-package isolation testing against minimum versions**

The definitive fix is a CI step that tests each package in a clean, isolated environment using only the minimum versions it declares. Concretely:

1. For each `projects/*/pyproject.toml`, resolve the `[project.dependencies]` lower bounds into an explicit pinned set: `dissect.util>=3.0` → install `dissect.util==3.0` from PyPI.
2. Create a fresh virtual environment containing *only* that package and its pinned minimum dependencies (no other workspace members, no extras, no dev groups).
3. Run the test suite against that environment.

A failure here means either: (a) a ghost dependency exists and must be declared, or (b) a lower bound is too loose and must be tightened to the version that actually introduced the API being used.

This test mode does not replace the standard workspace test run — it runs in addition to it, as a separate CI job (`test-isolation` or similar). It is slower and requires fetching historical versions from PyPI, but it needs to run only on packages whose `pyproject.toml` was changed in the PR, making it tractable.

This isolation testing is **not part of the current migration scope** but is documented here as a known gap in the constraint validation story.


