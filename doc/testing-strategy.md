# Plan: Dissect Monorepo — Testing Strategy

### Background

The monorepo hosts two categories of packages that have fundamentally different CI requirements:

- **Pure-Python packages** — no compiled extension; can be tested directly from source in the workspace environment.
- **Native packages** (currently `dissect.util` and `dissect.fve`) — contain a Rust extension that must be compiled before Python can import it. Testing them correctly requires validating two distinct things: that the Rust code integrates with its Python consumers, and that the resulting binary wheel can be packaged, installed, and executed correctly outside the workspace.

The testing strategy is therefore layered: a fast workspace-based test run gives broad functional coverage on every push and PR, and a separate wheel-build-and-test pipeline validates packaging correctness. A nightly job fills the architecture coverage gap left by the PR build.

---

### Job overview

| Job | Trigger | What it tests |
|---|---|---|
| `lint` | every push / PR | Formatting and static analysis |
| `test (variant=source)` | every push / PR | Pure-Python packages — all Python versions × OS |
| `test (variant=native)` | every push / PR | Native packages — Rust built in-place, workspace environment |
| `test-native` | every push / PR | Native packages — binary wheel built and tested in isolation, fast arches only |
| `test-native-full` | nightly (02:00 UTC) / manual | Same as `test-native` but all arches including QEMU |
| `docs` | every push / PR | Docstring completeness and API-reference build |

---

### Decision 1: Affected-only testing on push and PR

Running the full test suite for all 31 packages on every commit would be expensive even for pure-Python packages. Instead, the `test` job runs tests for the packages directly changed in the push or PR, plus every package that transitively depends on them.

**How it works**: `compute-base-ref.sh` determines the git commit to diff against:

| Event | Base ref |
|---|---|
| `pull_request` | The PR's base branch tip (`github.event.pull_request.base.sha`) |
| Regular push | The previous HEAD (`github.event.before`) |
| New branch push | Empty — falls back to running all tests |
| Force-pushed ref (before-SHA unreachable) | `HEAD^` (with a warning) |

The base ref is passed to `just test-affected` (or `just test-native-affected`). Rather than running only the directly changed packages, `affected_tests.py` builds a **reverse dependency graph** of the workspace and walks it transitively: a changed package triggers tests for itself *and* every package that (transitively) depends on it. When no base ref can be determined — a newly created branch, a force push that made the previous SHA unreachable — the job falls back to `just test-all`.

**Global triggers**: certain file changes are treated as affecting every package, regardless of which source files changed. If any of the following paths appear in the diff, all 31 packages are tested:

| Pattern | Rationale |
|---|---|
| `pyproject.toml` | Root config, dependency constraints, or test matrix changed |
| `uv.lock` | Resolved environment changed — any package could be affected |
| `Justfile` | Test invocation recipes changed |
| `.monorepo/**` | Test infrastructure scripts changed |
| `.github/workflows/**` | CI workflow definitions changed |

**Practical impact**: a PR that touches only `dissect.cstruct` runs tests for `dissect.cstruct` *plus* every package that imports it — `dissect.etl`, `dissect.executable`, and any other transitive dependents. A change to `dissect.util`, which sits near the root of the dependency graph, will trigger tests for a large fraction of the workspace. A change to a leaf package with no dependents (e.g. `dissect.thumbcache`) runs only that package's tests.

**Known limitation — affected testing assumes a green base**: the PR diff is computed against `base.sha` (the tip of the target branch). If a package was already failing on master *before* the PR was opened, it will not appear in the diff and its tests will not run. A clean PR build therefore means "this PR introduced no new failures", not "the entire codebase is healthy". This is an accepted trade-off, widely used in large monorepos (Nx, Turborepo, Bazel/Buck, Google TAP all work the same way). The correctness invariant holds only when master is green; a failing nightly run should therefore be treated as a blocker and resolved before further PRs are merged. The nightly `test-native-full` job (which runs `test-all`) is the authoritative signal that the full codebase is healthy.

---

### Decision 2: Two complementary test modes for native packages

Testing a Rust extension requires a compiled binary. There are two fundamentally different ways to produce that binary for test purposes, and they validate different things.

#### Mode A — In-place build (`variant=native` in the `test` job)

The `variant=native` matrix entries install a Rust toolchain (`dtolnay/rust-toolchain@stable`) and compile the Rust extension directly in the source tree, in the same step that runs the tests. The extension is loaded from its build directory, not from an installed wheel. This is done via `setuptools-rust`'s `build_ext --inplace` command, which is the same workflow a developer uses locally.

**Strengths**:
- Compiles and runs in a single step — fast feedback.
- Tests run inside the full workspace environment, so all Python consumers of the native extension (e.g. packages that import `dissect.util._rust`) are present and exercised together.
- Covers the same Python version × OS matrix as the pure-Python test run (5 Python versions × 2 operating systems = 10 combinations for affected native packages).
- The `DISSECT_FORCE_NATIVE` flag ensures tests that can fall back to a pure-Python implementation are forced to exercise the Rust path.

**Weaknesses**:
- The build produces a raw compiled artifact, not a wheel. Wheel-level metadata, entry points, platform tags, and the stable-ABI (`abi3`) constraint are never exercised.
- Running inside the workspace means all other workspace members are on the Python path regardless of declared dependencies — the same masking problem described in the release strategy applies here (see "Ghost Dependencies").
- Does not test installation from a wheel or pip-installability.

#### Mode B — Isolated wheel build and test (`test-native` / `test-native-full`)

The `build-native-wheels.yml` reusable workflow builds a real binary wheel using [cibuildwheel](https://cibuildwheel.readthedocs.io/) and runs the test suite against the installed wheel inside cibuildwheel's isolated build environment. Each package is installed from its own wheel, with only its declared dependencies — no other workspace members, no dev tooling.

**Strengths**:
- Tests the exact artifact that will be published to PyPI: correct wheel tags, stable-ABI compliance, embedded Rust binary, RPATH/linking.
- The isolated environment catches ghost dependencies (see release strategy) — if the package accidentally relies on something pulled in by the workspace but not declared, tests will fail.
- Exercises the `abi3` stable-ABI path used for production wheels (CPython 3.10+). The in-place build (Mode A) compiles without `--py-limited-api` and produces a version-specific `.so`; cibuildwheel compiles with `--py-limited-api=cp310` and exercises the actual production code path.
- Covers a wider platform matrix than the `test` job: Linux aarch64, macOS arm64, macOS x86_64, Windows amd64, Windows x86 — all without QEMU.

**Weaknesses**:
- Slower per platform: cibuildwheel installs Rust, compiles the extension, packages the wheel, and sets up an isolated virtual environment before running a single test.
- Cannot cheaply vary the Python version matrix — cibuildwheel runs across all supported Python versions (CPython 3.10–3.14, PyPy 3.11, free-threaded CPython) in a single job; the per-version granularity of `test` is not replicated here.
- Does not see other workspace packages during testing, so integration tests that require multiple dissect packages will not run in this mode.

#### How the two modes complement each other

| | In-place (`variant=native`) | Isolated wheel (`test-native`) |
|---|---|---|
| Speed | Fast | Slower |
| Tests integration with other packages | Yes (workspace visible) | No (isolated install) |
| Tests wheel packaging | No | Yes |
| Tests stable ABI (`abi3`) | No | Yes |
| Tests ghost dependency exposure | No | Yes |
| Platform coverage | Ubuntu, Windows | Linux x86_64, Linux aarch64, macOS, Windows |
| Python version coverage | 5 versions + PyPy | All cibuildwheel-supported versions |

Together: the in-place mode catches functional regressions quickly and validates that the Rust extension works with its Python consumers; the isolated wheel mode validates that the packaged artifact is correct and self-contained. A failure in one mode but not the other is a meaningful signal — in-place passes but wheel fails typically means a packaging or ABI issue; wheel passes but in-place fails typically means a Rust API regression affecting consumers.

---

### Decision 3: Fast and slow architectures

The native wheel build matrix covers many architectures. Not all of them can run natively on GitHub-hosted runners.

**Fast architectures** (native execution, no emulation):

| Architecture | Runner |
|---|---|
| `linux/x86_64`, `linux/i686` | `ubuntu-latest` (x86_64) |
| `linux/aarch64` | `ubuntu-24.04-arm` (native ARM runner) |
| `macOS arm64` | `macos-latest` |
| `macOS x86_64` | `macos-15-intel` |
| `Windows amd64` | `windows-latest` |
| `Windows x86` | `windows-latest` (cross-compile) |

These run at full hardware speed. The `linux/aarch64` entry uses GitHub's ARM-native runner and requires no emulation.

**Slow architectures** (QEMU-emulated):

| Architecture | QEMU platform |
|---|---|
| `linux/ppc64le` | `linux/ppc64le` |
| `linux/s390x` | `linux/s390x` |
| `linux/armv7l` | `linux/arm/v7` |

These CPUs have no corresponding GitHub-hosted runner. [`docker/setup-qemu-action`](https://github.com/docker/setup-qemu-action) registers the QEMU user-mode binary with the kernel's `binfmt_misc` subsystem, after which the Linux kernel transparently routes any execution of a matching ELF binary through QEMU. The build and test processes then run as if on the target CPU — but at whatever speed QEMU can simulate it. For Rust compilation (a CPU-intensive workload), emulation overhead can make a build 10–30× slower than a native run. Compiling a moderately sized Rust crate that takes 30 seconds on x86_64 can take 5–10 minutes under QEMU/s390x.

**The trade-off**: including QEMU arches on every PR would unacceptably inflate PR feedback time. Excluding them entirely would mean shipping wheels for `ppc64le` and friends without ever having tested them. The solution is the PR/nightly split.

**Arch lists are not hardcoded in the workflow** — they live in `pyproject.toml` under `[tool.monorepo.native]`:

```toml
[tool.monorepo.native]
linux-x86-archs-pr = ["x86_64"]
linux-x86-archs    = ["x86_64", "i686", "ppc64le", "s390x", "armv7l"]
```

Adding or removing an architecture only requires editing this file.

---

### Decision 4: Nightly full-arch build

The nightly job (`test-native-full`) runs `build-native-wheels.yml` with `include-slow-arches: true` on a schedule (`cron: "0 2 * * *"`, 02:00 UTC). It builds and tests native wheels for all architectures, including the QEMU-emulated ones.

**What it covers that PR builds do not**:
- `i686`, `ppc64le`, `s390x`, `armv7l` Linux wheels.
- The full arch list is always sourced from `linux-x86-archs` in `pyproject.toml`, so whatever is configured there is exactly what gets released and tested nightly.

**Failure handling**: nightly failures do not block merges. They signal a regression on an emulated arch that requires investigation before the next release. Because the release workflow (`release-native.yml`) also builds all arches, a regression caught nightly will also surface at release time — the nightly job simply finds it earlier.

The full-arch run can also be triggered manually via `workflow_dispatch` with `full-native: true`, which is useful when a PR specifically changes something arch-sensitive (e.g. endianness handling, 32-bit integer arithmetic) and the developer wants immediate confirmation without waiting for the nightly window.

---

### Decision 5: Work distribution across runners

The CI pipeline is designed so that all work that can run in parallel does run in parallel.

#### `test` job: Python version × OS × variant matrix

The test matrix is generated dynamically from `pyproject.toml` by `python_versions.py` and produces:

```
python-versions: ["3.10", "3.11", "3.12", "3.13", "pypy3.11"]
os:              ["ubuntu-latest", "windows-latest"]
variant:         ["source", "native"]
```

GitHub Actions takes the Cartesian product: `5 × 2 × 2 = 20 runners`. Each runner receives only the packages it needs to test (affected subset or all), installs the workspace, and runs independently. `fail-fast: false` ensures that a failure in one combination does not cancel the others.

#### `build-native-wheels.yml`: one runner per platform/arch

The native wheel build matrix is generated by `resolve_linux_archs.py`. The key design decision is that **each Linux x86 arch gets its own runner**. Without this, cibuildwheel would run multiple QEMU arches sequentially on a single runner, with each arch waiting for the previous one to finish. By splitting them, `i686`, `ppc64le`, `s390x`, and `armv7l` builds all start at the same time and run concurrently on separate runners.

For a PR build (`include-slow-arches: false`) the matrix is:

| Runner | Arch(es) |
|---|---|
| `ubuntu-latest` | `linux/x86_64` |
| `ubuntu-24.04-arm` | `linux/aarch64` |
| `macos-latest` | `macOS arm64` |
| `macos-15-intel` | `macOS x86_64` |
| `windows-latest` | `Windows amd64`, `Windows x86` |

For a nightly or release build (`include-slow-arches: true`) the QEMU arches each add one more `ubuntu-latest` runner to the above.

#### Concurrency control

The `CI` workflow uses a concurrency group keyed on `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true`. This means that pushing two commits to the same branch in quick succession cancels the CI run for the first commit and starts fresh for the second. Only the release workflow (`release.yml`) uses `cancel-in-progress: false` — an in-progress release must never be preempted.

---

### Decision 6: cibuildwheel configuration

cibuildwheel is configured centrally in the root `pyproject.toml` under `[tool.cibuildwheel]` and is shared by all native packages. Key points:

**Stable ABI (`abi3`) wheels**: wheels are built with `--py-limited-api=cp310`, which produces a single `cp310-abi3` wheel that works on CPython 3.10 through any future 3.x. This halves the number of wheel files to publish (one per platform instead of one per platform × Python version) and is the standard approach for Rust extensions that do not rely on CPython-version-specific internals.

**Free-threaded CPython exception**: `cp3??t-*` (free-threaded) builds are opted into via `enable = ["cpython-freethreading"]` but cannot use the stable ABI — an override drops `--py-limited-api=cp310` for those targets only.

**PyPy**: opted into via `enable = ["pypy", "pypy-eol"]`. PyPy cannot use the stable ABI either, but cibuildwheel's defaults handle this correctly.

**Skipped targets**: several musl targets (`musllinux_i686`, `musllinux_ppc64le`, `musllinux_s390x`, `musllinux_armv7l`) are skipped because they have no viable Rust cross-compilation support in the cibuildwheel toolchain.

**Test command**: cibuildwheel runs `pytest --force-native {package}/tests` inside each isolated wheel environment. The `--force-native` flag is equivalent to `DISSECT_FORCE_NATIVE=1` — it ensures tests target the Rust code path and do not silently fall back to the pure-Python implementation.

---

### Decision 7: Docs-check — explicitly pin Sphinx to 8.x

Every project in the monorepo ships a `tests/_docs/` directory containing a minimal [Sphinx](https://www.sphinx-doc.org/) configuration. This directory is not a documentation publisher — it is a **docstring linter**. The `docs` CI job runs `sphinx-build --fail-on-warning` across all projects to enforce that the API reference can be built cleanly.

**How it works**: `.monorepo/docs-check.sh` iterates over every `projects/*/tests/_docs/` directory and runs:

```
sphinx-build -b html -jauto -w <builddir>/warnings.log --fail-on-warning <sourcedir> <builddir>/html
```

All projects are built sequentially. Failures are collected and reported together at the end so that a single run surfaces all broken projects rather than stopping at the first one.

**Why `--fail-on-warning`**: Sphinx-autoapi emits a warning for every undocumented public symbol and for any docstring that contains invalid RST. Without `--fail-on-warning` these warnings are silent — a missing docstring or broken markup goes unnoticed. Treating warnings as errors turns the build into an active enforcement mechanism rather than a passive report.

**`imported-members` disabled in `autoapi_options`**: sphinx-autoapi's `imported-members` option causes every symbol re-exported via `__init__.py` to be documented at *both* the re-export location (`dissect.foo.Baz`) and the original definition location (`dissect.foo.bar.Baz`). The dissect packages use re-exports pervasively, so this produces duplicate object description warnings across the entire monorepo. Removing `imported-members` from `autoapi_options` is the correct fix: autoapi documents each symbol exactly once, at the module where it is defined.

**`suppress_warnings` for the autoapi import-resolution false-positive**: sphinx-autoapi uses astroid to resolve import chains during the "Mapping Data" phase — before any rendering decisions are made. When a package imports a symbol from a sibling dissect package (e.g. `from dissect.util import ...`), astroid walks up the `dissect` namespace to find its `__init__.py`. Because `dissect` is an implicit namespace package (PEP 420 — no `__init__.py` at the top level), astroid cannot anchor the namespace and emits `autoapi.python_import_resolution`. This happens regardless of whether `imported-members` is enabled or not: disabling `imported-members` stops the duplicate-documentation problem, but the import-resolution step that precedes it still runs and still fails on every cross-package import. Every `conf.py` therefore suppresses this category:

```python
suppress_warnings = [
    # https://github.com/readthedocs/sphinx-autoapi/issues/285
    "autoapi.python_import_resolution",
]
```

This suppression is enforced uniformly across all projects by `update_project_src_layout.py`'s `_fix_docs_conf_suppress_warnings()` function.

**Dependencies**: the `docs` CI job uses a dedicated `docs` dependency group in the root `pyproject.toml`:

```toml
[dependency-groups]
docs = ["sphinx>=8,<9", "sphinx-autoapi", "sphinx_argparse_cli", "furo"]
```

Sphinx is pinned to `>=8,<9`. Sphinx 9 introduced a new `ref.python` cross-reference fallback (issue #10785) that, when resolving a `:class:\`type\`` reference in a signature like `type_: type[T]`, searches the entire object registry for attributes named `type` if no class by that name is found. Code that happens to define multiple attributes with the same unqualified name (common in the dissect codebase) triggers a spurious "more than one target found" warning that fails the build. Sphinx 8 does not perform this broader search and silently ignores unresolved `:class:\`type\`` references. Until either sphinx-autoapi avoids emitting the `:class:\`type\`` role for builtin types, or a project-wide intersphinx mapping is added so Sphinx can resolve `type` to `builtins.type` without searching the object registry, **upgrading Sphinx beyond 8.x will break the docs linter**.

---

### Known gaps

**Ghost dependency detection**: as described in the release strategy, sources-based tests (both `variant=source` and `variant=native`) run inside the shared workspace environment and cannot distinguish declared from undeclared dependencies. The `just test` recipe uses `uv run --all-packages`, which installs all 31 workspace members as editables and puts all their `src/` directories on `sys.path`. A package can therefore silently import a sibling it never declared as a dependency, and tests will pass.

An alternative is `uv run --package <pkg>`, which installs only the target package and its declared dependency closure — undeclared workspace siblings are genuinely absent from `sys.path` since each package lives in its own `projects/<pkg>/src/` directory. This provides meaningful ghost-dependency isolation at the workspace-sibling level — an undeclared sibling import will fail rather than silently succeed. It does not, however, catch version constraints that are set too low: `[tool.uv.sources]` always resolves workspace members to their local copy regardless of the declared version bound, so a package that declares `dissect.cstruct>=4.0` but relies on an API introduced in 4.6 will still pass. The drawback is that `--package` scopes the environment entirely to the target package's own metadata, so the root `pyproject.toml`'s `[dependency-groups]` (which supply `pytest` and `pytest-xdist`) are ignored. Pytest must then be injected via `--with "pytest>=8.4.0" --with "pytest-xdist>=3"`, moving test-tooling version constraints out of `pyproject.toml` and into the Justfile. The current recipe uses `--all-packages` because the ghost-dep risk across this codebase is low in practice — all packages are maintained together and imports are well-understood — and keeping test dependencies centrally declared in `pyproject.toml` is considered more maintainable than scattering them into recipe arguments. If ghost-dep detection becomes a concern, switching to `--package` with explicit `--with` overrides is a straightforward change.

The isolated wheel tests partially close this gap for native packages, but no equivalent isolation exists for pure-Python packages in the standard test run. Per-package isolation testing against minimum declared versions remains out of scope for the current migration.

**Integration tests across native and pure-Python packages**: the isolated wheel test environment contains only the package under test and its declared dependencies. Any test that exercises the interaction between, say, `dissect.util` (native) and `dissect.target` (pure-Python) will only run in `variant=source` or `variant=native` — not in the wheel isolation mode.
