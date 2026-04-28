# Justfile Recipe Reference

Run `just --list` at any time for a quick summary. This document gives fuller descriptions and user journey guides.

---

## Recipe overview

### Testing

#### `just test <project> <env> [args]`

Run pytest for a single project using the given Python version. All workspace members are installed as editable so sibling dependencies are importable. Optional extra pytest arguments can be passed as the third argument.

```
just test dissect.xfs 3.11
just test dissect.xfs 3.11 "-k test_foo"
```

#### `just test-all [env] [args]`

Run pytest for every project in `projects/` using the given Python version (default: `3.10`). Skips directories without a `pyproject.toml`.

```
just test-all 3.12
just test-all 3.10 "-k test_foo"
```

#### `just test-all-envs`

Run `test-all` for every Python version listed in `[tool.monorepo.test].python-versions` in `pyproject.toml`. Used by CI to cover the full version matrix.

#### `just test-affected [ref] [env]`

Run tests only for packages whose source files changed relative to `ref` (default: `origin/master`) using the given Python version (default: `3.10`). The list of affected packages is computed by `.monorepo/affected_tests.py`.

```
just test-affected origin/master 3.11
```

#### `just test-native <project> <env> [args]`

Build the Rust extension for a single native project in-place, then run its tests with `DISSECT_FORCE_NATIVE=1` so the test suite fails (rather than silently skipping) if the compiled extension cannot be imported.

```
just test-native dissect.util 3.12
just test-native dissect.util 3.12 "-k test_lz4"
```

#### `just test-native-all [env]`

Build all Rust extensions in-place, then run the full test suite with `DISSECT_FORCE_NATIVE=1`.

#### `just test-native-affected [ref] [env]`

Build all Rust extensions in-place, then run tests only for affected packages with `DISSECT_FORCE_NATIVE=1`. All extensions are always built (not only affected ones) so that non-affected native packages are available as compiled dependencies for the packages under test.

---

### Building native extensions

#### `just build-native-inplace <project> [env]`

Compile the Rust extension for a single native project in-place using `setuptools-rust`. The resulting `.so` lands directly under `src/`, where the uv editable install can find it. Requires `cargo`/`rustup` installed locally.

```
just build-native-inplace dissect.util 3.12
```

#### `just build-all-native-inplace [env]`

Compile all native extensions in-place. Iterates over the project list from `.monorepo/native_projects.py`.

#### `just build-native-wheels <pkg> [archs]`

Build production wheels (abi3 + free-threaded) for a single package via cibuildwheel. The `CIBW_BUILD` specifier is derived from `python-versions` in `pyproject.toml` via `.monorepo/python_versions.py`. After building, runs `abi3audit` on any abi3 wheels to verify stable-ABI compliance. Requires Docker (or Podman) for Linux builds.

`archs` defaults to `"auto"` (host architecture only). Pass a space-separated list to build for additional platforms — callers are responsible for configuring QEMU first.

```
just build-native-wheels dissect.util
just build-native-wheels dissect.util "x86_64 i686 aarch64"
```

Wheels land in `dist/<pkg>/`.

#### `just test-native-wheels [archs] [packages]`

Build wheels for all native projects (or a specified subset) and run their tests in the built wheels via cibuildwheel's built-in test step. Used by CI on every push/PR to validate the full wheel pipeline locally or in GitHub Actions.

```
just test-native-wheels                                         # host arch, all native packages
just test-native-wheels "x86_64 i686 aarch64"                  # multi-arch (caller configures QEMU)
just test-native-wheels auto "dissect.util dissect.fve"         # specific packages only
```

---

### Releasing

#### `just release <packages|all> [--index testpypi]`

Publish pending workspace packages to PyPI, then create and push git tags. Only pure-Python packages — native (Rust) packages are released via the `release-native.yml` GitHub Actions workflow.

Pass `all` to release every package that has a pending (untagged) version, or list package names explicitly. Pass `--index testpypi` to publish to TestPyPI for a dry run.

For authentication, set `UV_PUBLISH_TOKEN=<token>` locally. CI uses OIDC Trusted Publishing and needs no token.

```
just release all
just release dissect.util dissect.cstruct
just release all --index testpypi
```

#### `just bump <packages|all|auto>`

Bump the minor version of one or more workspace packages and regenerate `uv.lock`. Pass `all` to bump every workspace member, or `auto` to bump only packages that have new commits since their last release tag.

**Guard**: when bumping named packages or `all`, refuses to bump any package whose current version has no release tag yet — release pending versions first to avoid double-bumps. `auto` silently skips pending packages instead of erroring.

```
just bump dissect.util dissect.cstruct
just bump all
just bump auto
```

#### `just pending-releases [--names]`

List workspace packages whose current version has no corresponding git release tag (i.e. not yet published). Pass `--names` to get a bare newline-separated list of package names, suitable for scripting.

#### `just set-constraint <package> <specifier>`

Update the version specifier for an internal dependency across every project that already declares it. Runs `uv lock` afterward to keep the lockfile consistent.

```
just set-constraint dissect.cstruct ">=4.7,<5"
```

#### `just update-meta`

Regenerate the dependency list of the `dissect` meta-package from current workspace versions. Run this before releasing `dissect` to ensure it points at the latest versions of all member packages.

---

### Code quality

#### `just lint`

Run `ruff check`, `ruff format --check`, and `vermin` over all projects. Reports problems without modifying any files.

#### `just fix`

Auto-fix ruff issues (check + format). `vermin` has no auto-fix mode.

#### `just ruff [fix]`

Run ruff check and format. Pass `fix="true"` to apply fixes; default is report-only.

#### `just vermin`

Run `vermin` to verify that no project uses Python features newer than the declared minimum version (`3.10`).

---

### Maintenance

#### `just clean`

Remove all built wheels and sdists from the `dist/` directory. Refuses to run if `dist/` is a symlink.

#### `just docs-check`

Build the Sphinx API-reference docs for every project that has a `tests/_docs/` directory and fail if sphinx-build emits any warnings. All workspace packages are installed as editable so autoapi can resolve imports across sibling projects. Used by CI on every push/PR.

```
just docs-check
```

#### `just docs-clean`

Remove all Sphinx build artefacts — the pickled environment (`tests/_docs/build/`) and the autoapi-generated RST files (`tests/_docs/api/`) — for every project. The next `just docs-check` will then start from a clean slate.

Run this whenever you change `conf.py` or `autoapi_options` to prevent Sphinx from reusing stale cached output. CI never needs this because each runner starts fresh.

```
just docs-clean
just docs-clean && just docs-check   # clean rebuild
```

---

## User guides

### Day-to-day development

1. Make changes to one or more projects.
2. Run `just test <project> <env>` to check a single project quickly.
3. Run `just test-affected` before pushing to check all projects touched by your diff.
4. Run `just lint` to verify formatting and minimum-version compliance.

### Releasing a pure-Python package

1. **Bump the version** — only if the current version has already been released:
   ```
   just bump dissect.util
   ```
   Commit the `pyproject.toml` and `uv.lock` changes together with the work that motivates the bump.

2. **Tighten a downstream constraint** (only if a new minimum is required):
   ```
   just set-constraint dissect.util ">=3.25,<4"
   ```
   Commit the changes and updated `uv.lock`.

3. **Dry-run to TestPyPI** (optional but recommended for a first release or structural changes):
   ```
   just release dissect.util --index testpypi
   ```

4. **Release to PyPI**:
   ```
   just release dissect.util
   ```
   The script publishes the wheel and sdist, then creates and pushes a git tag `dissect.util-<version>`.

5. **Update the meta-package** (if releasing `dissect` itself, or after bulk releases):
   ```
   just update-meta
   just release dissect
   ```

### Releasing a batch of packages

1. **Auto-bump all packages with new commits** since their last release:
   ```
   just bump auto
   ```
   This bumps every package that has a release tag for its current version and new commits since that tag. Packages that were already manually bumped (and are therefore pending release) are silently skipped.

2. **Check what is pending**:
   ```
   just pending-releases
   ```

3. **Release all pending packages**:
   ```
   just release all
   ```

### Releasing a native (Rust) package

Native packages cannot be released with `just release` because they require platform-specific wheels built by cibuildwheel. Instead:

1. Bump the version and commit as above.
2. Trigger the `release-native` GitHub Actions workflow manually (`workflow_dispatch`), specifying the package name. The workflow builds wheels for all platforms and architectures, runs `abi3audit`, and publishes to PyPI via OIDC Trusted Publishing.

To validate the wheel pipeline locally before triggering the workflow:
```
just test-native-wheels auto dissect.util
```

### Testing across all Python versions

```
just test-all-envs
```

This runs the full test suite for every Python version in `[tool.monorepo.test].python-versions`. Equivalent to what CI runs on push/PR.
