# Plan: Dissect Monorepo — Release Strategy

### Background

All 31 `dissect.*` projects have been migrated from individual repositories into a single uv workspace monorepo. Each project is still built and released as an independently published PyPI distribution. The monorepo provides:

- A single place to develop and make cross-cutting changes
- Shared tooling: formatting (ruff), linting (vermin), testing (pytest-xdist), CI (GitHub Actions)
- Workspace-level dependency resolution during development — `[tool.uv.sources]` wires every `dissect.*` dependency to the local workspace copy, so published version bounds don't interfere with day-to-day work

---

### Terminology

This document distinguishes three concepts that are all loosely called "package" elsewhere:

- **project** — a workspace member: a source tree with its own `pyproject.toml`, version-bumped, released, and tagged as a unit (e.g. the `dissect.util` folder under `projects/`).
- **distribution** (**sdist** / **wheel**) — the artifact built from a project, published to PyPI and installed by users.
- **import package** — an importable directory (e.g. `dissect/cstruct/`); in this repo these are PEP 420 namespace packages.

---

### Decision 1: Version bumping stays manual

**Approach**: Developers bump the `version` field in a project's `pyproject.toml` directly, as they did before. No automation determines *what* the next version number should be.

**Rationale**: Tools like `python-semantic-release` or `commitizen` can be valuable — deriving version increments from commit message conventions (Conventional Commits: `feat:`, `fix:`, `chore:` etc.) reduces manual overhead and makes the release history machine-readable. However, adopting them would require migrating all contributors to a new commit discipline and adding tooling to every project. That is a worthwhile change to evaluate on its own terms, but it is independent of the monorepo migration and would add significant scope to it.

Introducing automated version bumping is therefore **out of scope for this migration**. The version decision remains manual, as it was before. What changes is the mechanics: in the per-repo workflow the version was dynamic, derived from a git tag at build time — pushing a tag *was* the release act. In the monorepo, tags no longer drive individual project releases, so the version is instead a static field in each project's `pyproject.toml`, edited directly before publishing.

**Why tags do not trigger releases in the monorepo**: restoring the tag-as-trigger model would require CI to write the version back into `pyproject.toml` (and regenerate `uv.lock`) and push that commit to `main`. This creates several compounding problems: CI needs write access and the push must bypass branch protection rules; the machine-generated commit appears in `git log` and `git blame`; pushing 10 release tags simultaneously fires 10 independent concurrent workflows with no coordination between them; and any failure mid-way leaves `pyproject.toml` out of sync with the published state. The `workflow_dispatch` trigger avoids all of this — it provides the same explicit "I am intentionally releasing now" signal, while leaving version management in the developer's hands and keeping CI read-only with respect to the repository.

`just bump` and `just bump-patch` recipes will handle the mechanical part — they increment the `version` field in the `pyproject.toml` of one or more projects:

```
just bump dissect.util dissect.cstruct      # minor bump of specific projects
just bump auto                              # minor bump all projects with new commits
just bump-patch dissect.util               # patch bump a single project
just bump-patch dissect.util dissect.cstruct  # patch bump specific projects
```

`just bump` and `just bump auto` always bump the **minor** component (and reset patch to zero). `just bump-patch` increments only the **patch** component and does not support `auto` — patch bumps always require explicit project names. Both recipes run `uv lock` after editing `pyproject.toml` files so the workspace lockfile stays consistent.

**Preventing double-bumps**: a developer who bumps a version but does not immediately publish creates an invisible pending state — a second developer (or the same one, later) may bump again without realising the first bump has not been released yet. Both `bump` and `bump-patch` enforce this guard by **reusing the same pending-releases check** used by `just release`: before making any changes, they call into the pending-releases logic to determine whether the current local version of each target project already has a corresponding release tag. If no tag exists, the version has never been released and the recipe aborts with an error. The developer is prompted to either release the pending version first or explicitly bundle the new work under it. Version bumps should only be committed together with the feature or fix that motivates them, not as speculative pre-bumps.

---

### Decision 2: No automatic dependency constraint propagation — with one exception

**Approach**: When a developer adds a feature to `dissect.util` and wants to declare that downstream projects require at least that version, they update the lower bound manually in the affected `pyproject.toml` files. A `just set-constraint` recipe will make this a single command rather than a manual edit across N files.

**Exception**: The `dissect` meta-project is a pure aggregator with no source code — its sole purpose is to pull in all 31 `dissect.*` projects. Because it carries no logic of its own, its dependency constraints have no semantic meaning beyond "point at what's current". Its constraints will therefore be **calculated automatically**: a script reads the `version` field from each workspace member's `pyproject.toml` and generates pinned lower bounds of the form `dissect.util>=3.24,<4` for each entry. This script runs as part of the release workflow, just before building and publishing the meta-project.

**Rationale**: Analysis of all internal `dissect.*` dependencies across the 31 projects shows that the vast majority use **loose major-version lower bounds** (`>=3,<4`, `>=4,<5`, etc.). Under this scheme, any minor release is automatically compatible with all downstream consumers — no propagation is needed. Propagation is only relevant when a developer intentionally tightens a lower bound to mandate a new minimum minor version, which is a deliberate, infrequent decision. When that decision is made, `just set-constraint` makes the mechanical part a single command — it updates the specifier across every `pyproject.toml` that already declares the dependency — so the developer can focus on the intent rather than hunting down files. The recipe runs `uv lock` afterward to keep the workspace lockfile consistent with the updated constraints.

---

### Decision 3: Release detection via git tags

**Problem**: In the old per-repo workflow, pushing a git tag immediately triggered a release pipeline. In the monorepo, version bumps are commits and there is no per-project tag-triggered release. We need a way to determine which projects have unpublished local versions before running `uv publish`.

**Approach**: A `pending-releases.py` script determines pending projects by comparing each workspace member's local `version` field to the set of existing git tags. A project is pending if no tag of the form `<name>/<version>` exists for its current local version. This check is fully offline and instant.

```
$ python pending-releases.py
dissect.util        3.24.1  →  no tag (pending)
dissect.database    3.24.0  →  tagged (published)
...
```

A corresponding `just release` recipe would: (1) run `pending-releases.py` to enumerate what needs publishing, (2) build and publish each pending project via `uv publish`, (3) create a namespaced git tag `dissect.util/3.24.1` for each project successfully published. The tags provide a permanent release record and enable future changelog generation via `git log dissect.util/3.24.1..HEAD -- projects/dissect.util/`.

**Non-authoritative by design**: the tag-based check assumes that `just release` is the only publication path. If a project is published manually without going through the recipe (and thus without creating a tag), it will appear pending again and `uv publish` will return a 409 conflict — a visible, recoverable error. The fix is to create the missing tag manually. This is acceptable because manual out-of-band publishing is not part of normal workflow.

This same logic is reused by `just bump` and `just bump-patch` as the double-bump guard (see Decision 1).

The recipe accepts an optional space-separated list of project names to restrict the release to a subset:

```
just release dissect.util dissect.cstruct
```

When no projects are specified, all pending projects are released.

The GitHub Actions `workflow_dispatch` trigger supports typed form inputs, which GitHub renders as a proper form in the UI when manually triggering a workflow. A `string` input is used to pass the optional project list:

```yaml
on:
  workflow_dispatch:
    inputs:
      packages:
        description: 'Space-separated list of projects to release (leave empty for all pending)'
        required: false
        default: ''
        type: string
```

The workflow then forwards the value directly to the recipe:

```yaml
- run: just release ${{ inputs.packages }}
```

Leaving the field blank in the UI releases everything pending; filling it in restricts the run to the named projects.

**Alternatives considered**:
- *Upload all, skip existing* (`uv publish --skip-existing`): simpler to operate but builds all 31 projects every time, even when nothing changed.
- *PyPI JSON API query*: authoritative — reflects actual published state regardless of tag discipline — but requires a network call for all 31 projects on every run. Retained as a fallback option if the tag-based approach causes false positives in practice.

---

### Decision 4: GitHub Actions release workflow and authentication

**Workflow**: `config/.github/workflows/release.yml` (applied to the monorepo via `install_config.sh`) exposes `just release` as a manually triggered GitHub Actions workflow. It accepts two inputs rendered as form fields in the GitHub UI:

| Input | Default | Description |
|---|---|---|
| `packages` | `all` | Space-separated project names, or `all` for every pending project |
| `target` | `production` | Release role: `production` (tagged, triggers native wheel builds) or `test` (upload-validation dry run, not tagged, native skipped) |

The `target` input is a **release role**, not a raw index name. Each role maps to a `[[tool.uv.index]]` name via `[tool.monorepo.release]` in the root `pyproject.toml` (`production-index`, default `pypi`; `test-index`, default `testpypi`). Decoupling the role from the index keeps the *semantics* (is this a real release?) separate from the *destination* (which registry), so the production role can point at any registry and only production releases are tagged. Because git tags are the canonical release ledger that pending-release detection and the native wheel trigger both key off, a `test` release deliberately publishes **without** creating a tag — it validates the upload path only.

A concurrency group (`group: release`, `cancel-in-progress: false`) ensures that at most one release workflow runs at a time and that an in-progress release is never cancelled by a concurrent trigger.

**GitHub App token — why it is required**

After successfully publishing a project, `release.yml` pushes a namespaced git tag (e.g. `dissect.util/3.24.1`) to `main`. That tag push is what triggers `release-native.yml` to build and publish binary wheels automatically.

GitHub intentionally suppresses workflow triggers when a push is made with the built-in `GITHUB_TOKEN`: a tag pushed by `GITHUB_TOKEN` will *not* fire any `push: tags`-triggered workflow. This guard exists to prevent accidental infinite loops, but it also means the native wheel pipeline would never start automatically.

The workaround is a **GitHub App installation token**. Pushes authenticated with an app token are attributed to the app (a non-workflow actor), so GitHub treats them like a real user push and fires downstream workflows normally. The workflow mints a fresh, short-lived installation token at the start of each run via `actions/create-github-app-token`, using two repository-level secrets:

| Secret | Contents |
|---|---|
| `RELEASE_APP_ID` | The numeric ID of the GitHub App (found on its settings page) |
| `RELEASE_APP_PRIVATE_KEY` | The PEM-encoded private key generated for the app |

These are **repository-level** secrets (not environment secrets) because they are needed before the workflow selects an environment.

Setup: create a GitHub App (it can be scoped to a single repository), install it on the monorepo, grant it **Contents: Read & Write** permission, generate a private key, then store the app ID and private key as repository secrets named `RELEASE_APP_ID` and `RELEASE_APP_PRIVATE_KEY`.

The `target` role maps to a **GitHub environment** named `<role>_publish` (`production_publish` or `test_publish`). Environments serve two purposes here: they act as deployment gates (the `production_publish` environment can be configured to require a manual review before proceeding) and they scope secrets — `UV_PUBLISH_TOKEN` is stored per-environment so that the test-index token cannot accidentally be used to publish to the production index and vice versa.

**Authentication strategy — dual-mode**

The workflow supports two authentication modes and automatically selects between them at runtime:

1. **Account-scoped API token** (primary): If a secret named `UV_PUBLISH_TOKEN` is stored in the active GitHub environment, `uv publish` uses it directly. A single account-scoped token covers all 31 projects, so one token per index (pypi, testpypi) is sufficient.

2. **OIDC Trusted Publishing** (fallback): If no `UV_PUBLISH_TOKEN` secret is present in the environment, the workflow falls back to PyPI's [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) mechanism. The workflow is granted the `id-token: write` permission, which allows it to obtain a short-lived, cryptographically verifiable OIDC token from GitHub that PyPI accepts in place of a long-lived credential.


**Why account-scoped tokens instead of per-project Trusted Publishers**

PyPI Trusted Publisher setup requires clicking through a per-project form on pypi.org (one submission per project per index). With 31 projects and two indexes (pypi + testpypi) that is 62 one-time manual setup operations. PyPI provides no public API for this; it cannot be automated. An account-scoped API token is a single credential that covers all projects under the account, reducing the setup to one token per index regardless of how many projects exist.

OIDC Trusted Publishing remains available as a zero-credential fallback: once a Trusted Publisher is configured for a given project (if ever), the workflow will automatically use it when no `UV_PUBLISH_TOKEN` secret is set in the environment.

**Pending user actions — environment and secret setup**

The one-time setup of the GitHub environments (`production_publish` / `test_publish`), the `UV_PUBLISH_TOKEN` secrets, and the release GitHub App is described step by step in [setup.md](setup.md). Without that setup, releases cannot authenticate to the package index and tags pushed by `release.yml` will not trigger `release-native.yml` (see Authentication strategy above for the full explanation).


---

### Decision 5: Native (Rust) wheel publishing

**Scope**: A small subset of dissect projects (currently `dissect.util` and `dissect.fve`) contain a Rust extension that must be compiled into a platform-specific binary wheel for each supported OS / architecture combination. Pure-Python projects are unaffected — they are published as described in Decision 4.

**What marks a project as native**: `native = true` under `[tool.monorepo]` in the project's `pyproject.toml`. The `.monorepo/native_projects.py` script enumerates all such projects.

---

#### Relationship to pure-Python release

Native projects follow the **same version management rules** as pure-Python projects (Decision 1–3) and go through the same `just release` path (Decision 4). The difference is in what happens *after* a **production** `just release`:

1. `just release` publishes the **sdist** of each pending project to the production index and creates a namespaced tag (e.g. `dissect.util/3.24.1`).
2. Pushing that tag **automatically triggers** `release-native.yml` via the `push: tags` trigger.
3. That workflow builds binary wheels on all supported platforms and publishes them to the production index alongside the sdist.

In other words, no developer action is needed beyond the usual `just release` — the native wheel pipeline kicks in automatically.

**Native builds only run for production releases.** Because tags are pushed only for the production role (Decision 4), the `push: tags` trigger fires only for production — so native wheels are built exactly when a production tag appears, and there is no index to forward to `release-native.yml` (it always targets the production index). A `test` release publishes only the sdist for upload validation: it creates no tag and therefore builds no native wheels. (To build native wheels against the test index deliberately, dispatch `release-native.yml` manually with `target: test`.)

This two-step sequence is possible because PyPI treats a release (a version number) as a container that can receive additional distribution files after the initial upload. Publishing the sdist first does not close or lock the release; `release-native.yml` can add binary wheels to the same version later without any special API access or re-release mechanics.

**Publication window**: there is a brief period between the end of step 1 and the end of step 3 during which the project is live on PyPI but only the sdist is available. A user who installs the project in that window will receive the sdist and pip will attempt to build it from source, requiring a Rust toolchain. This is the same experience any user on an unsupported platform would have, and it is generally harmless. The window is short — `release-native.yml` is triggered immediately by the tag push and builds in parallel across platforms — but it is not zero.

---

#### Trigger: tag push vs. `workflow_dispatch`

`release-native.yml` has two triggers:

| Trigger | Use case |
|---|---|
| `push: tags` matching `**/[0-9]*` | Automatic — fires once per `<project>/<version>` tag pushed by a production `just release`; always targets the production index |
| `workflow_dispatch` | Manual fallback — e.g. retrying a skipped tag-triggered run, releasing a subset of native projects on demand, or building wheels against the test index (`target: test`) |

The `workflow_dispatch` form accepts:
- **`packages`** — space-separated project names or `all`
- **`target`** — release role: `production` (default) or `test`

---

#### GitHub App token — why it is required

GitHub Actions' `GITHUB_TOKEN` has a deliberate restriction: events fired by workflows that use `GITHUB_TOKEN` do **not** trigger subsequent workflow runs. This is an anti-loop safeguard built into GitHub Actions. In practice, if `release.yml` pushed the `dissect.util/3.24.1` tag using `GITHUB_TOKEN`, the `push: tags` trigger on `release-native.yml` would be **silently skipped** — no error, no warning, nothing.

A **GitHub App token** bypasses this restriction. A tag pushed with an App-minted token is treated by GitHub as a normal user push, so `push: tags` fires as expected.

**How `release.yml` uses it**: before checking out the repository, the workflow calls [`actions/create-github-app-token`](https://github.com/actions/create-github-app-token) to mint a short-lived (1-hour) installation token. `actions/checkout` is then passed that token, so every subsequent git operation in the job — including the tag push performed by `just release` — is authenticated as the GitHub App rather than as `GITHUB_TOKEN`.

**Required secrets** (stored at repository level, not inside a GitHub environment):

| Secret | Value |
|---|---|
| `RELEASE_APP_ID` | The numeric App ID shown on the GitHub App's Settings page |
| `RELEASE_APP_PRIVATE_KEY` | The full PEM contents of a private key generated for the App |

**Minimal permissions for the GitHub App**:

| Permission | Level |
|---|---|
| Contents | Read & write (to push tags) |
| Metadata | Read-only (automatic) |

No other permissions are required. No repository installation scope is needed beyond the single repository that runs `release.yml`.

---

#### Arch configuration

The set of Linux x86 architectures to build is **not hardcoded in the workflow** — it lives in `[tool.monorepo.native]` inside the root `pyproject.toml`:

```toml
[tool.monorepo.native]
linux-x86-archs-pr = ["x86_64"]                          # CI / PR builds (fast, no QEMU)
linux-x86-archs    = ["x86_64", "i686", "ppc64le", "s390x", "armv7l"]  # release builds
```

The `.monorepo/resolve_linux_archs.py` script reads these lists, derives the corresponding `docker/setup-qemu-action` platform string automatically, and emits GitHub Actions outputs. Adding or removing an architecture only requires editing `pyproject.toml`.

---

#### Pending setup for native projects

- **PyPI Trusted Publishers** (recommended): configure a Trusted Publisher for each native project on pypi.org under Account → Publishing. Without this, `UV_PUBLISH_TOKEN` must be set in the `production_publish` / `test_publish` GitHub environments (already required for pure-Python projects — the same token covers native projects too).


### Pending user actions

- **GitHub App** (required for native wheel automation): create a GitHub App with **Contents: Read & write** permission, install it on the repository, then add two repository-level secrets: `RELEASE_APP_ID` (numeric App ID) and `RELEASE_APP_PRIVATE_KEY` (PEM private key). Without these, the `push: tags` trigger on `release-native.yml` will not fire when `release.yml` pushes a tag. See Decision 5 — *GitHub App token* for details.
- Create `pypi` and `testpypi` GitHub environments in repository Settings → Environments (see Decision 4).
- Add `UV_PUBLISH_TOKEN` secret to each environment (account-scoped API token from pypi.org / test.pypi.org).
- Optionally add Required Reviewers to the `pypi` environment for a manual approval gate.
- Create a GitHub App and add `RELEASE_APP_ID` and `RELEASE_APP_PRIVATE_KEY` as repository-level secrets (see Decision 4 — Authentication strategy).


### Known Risk: Ghost Dependencies and the Workspace Masking Problem

**The problem**: A ghost dependency (sometimes called a phantom dependency) is an undeclared package that a project uses at runtime but does not list in `[project.dependencies]`. The package happens to be installed in the environment because something *else* pulled it in transitively. The code works, tests pass, but the published package is broken for any user whose environment doesn't include that transitive package — because there is no constraint to guarantee it will be present.

This is not a new problem, but the monorepo workspace makes it systematically harder to detect.

**How `[tool.uv.sources]` masks it**: When running tests inside the monorepo, `uv sync --all-packages` installs every workspace member into a single shared environment. This means `dissect.target`'s test environment contains `dissect.util`, `dissect.cstruct`, `dissect.ntfs`, and every other workspace member — regardless of whether `dissect.target` actually declares a dependency on them. A developer could accidentally import `dissect.ntfs` directly from `dissect.target` code, never declare it as a dependency, and all tests would pass locally and in CI. The bug only surfaces when an external user installs `dissect.target` from PyPI into a fresh environment that doesn't happen to have `dissect.ntfs`.

The same masking applies to version constraints. If `dissect.target` declares `dissect.util>=3.0` but actually uses an API introduced in `3.24`, tests always pass in the workspace because the workspace always resolves to the current local version of `dissect.util`. An external user pinned to `dissect.util==3.0` would get an `AttributeError`.

**The solution: per-project isolation testing against minimum versions**

The definitive fix is a CI step that tests each project in a clean, isolated environment using only the minimum versions it declares. Concretely:

1. For each `projects/*/pyproject.toml`, resolve the `[project.dependencies]` lower bounds into an explicit pinned set: `dissect.util>=3.0` → install `dissect.util==3.0` from PyPI.
2. Create a fresh virtual environment containing *only* that project and its pinned minimum dependencies (no other workspace members, no extras, no dev groups).
3. Run the test suite against that environment.

A failure here means either: (a) a ghost dependency exists and must be declared, or (b) a lower bound is too loose and must be tightened to the version that actually introduced the API being used.

This test mode does not replace the standard workspace test run — it runs in addition to it, as a separate CI job (`test-isolation` or similar). It is slower and requires fetching historical versions from PyPI, but it needs to run only on projects whose `pyproject.toml` was changed in the PR, making it tractable.

This isolation testing is **not part of the current migration scope** but is documented here as a known gap in the constraint validation story.


