# Plan: Dissect Monorepo — Tooling

### Background

The monorepo needs two categories of tooling: a **package manager** that understands the multi-project workspace and resolves dependencies across all 31 packages together, and a **task runner** that provides a consistent, discoverable set of commands for development, testing, releasing, and CI. Both choices were made to keep the setup as simple and approachable as possible while still supporting the full range of operations the monorepo requires.

---

### Decision 1: uv as package manager and workspace backend

**Approach**: [uv](https://docs.astral.sh/uv/) manages all Python environments, dependency resolution, locking, and package building. The 31 projects are declared as `[tool.uv.workspace]` members in the root `pyproject.toml`, which produces a single shared `uv.lock` covering all packages.

**Why uv**:

- *Speed*. uv is implemented in Rust and resolves and installs packages roughly an order of magnitude faster than pip. In a monorepo with 31 packages and hundreds of transitive dependencies, resolution and environment setup time is a visible CI bottleneck; uv keeps it negligible.
- *Workspace support*. `[tool.uv.workspace]` + `[tool.uv.sources]` provides first-class monorepo support: every `dissect.*` dependency is automatically wired to the local workspace copy during development and testing. Developers and CI never install from PyPI when a local version is present.
- *Single lockfile*. One `uv.lock` encodes the fully resolved environment for all 31 packages across all supported Python versions. This makes reproducibility trivial — `uv sync` gives every developer and every CI runner the same environment from a cold start.
- *`uv run`*. Scripts and tools can be invoked without manually activating a virtual environment. `uv run --python 3.11 pytest ...` selects the right interpreter, installs into (or reuses) a managed environment, and runs — all in one command. This is heavily used by CI recipes and the Justfile.

**Alternatives considered**:

- *pip + venv*: The baseline Python tooling. Fast enough for a single package but slow for 31, and has no workspace concept — all cross-package linking has to be done manually via `pip install -e`. No lockfile support without a separate tool (pip-tools, pip-compile).
- *Poetry*: Has lockfiles and limited workspace support (`packages` in `pyproject.toml`), but workspace support is an afterthought and the resolver is significantly slower than uv. Configuration is `pyproject.toml`-based but requires Poetry-specific metadata that diverges from the standard.
- *PDM*: Closer to the standard than Poetry, has PEP 582 support and workspaces, but materially less adoption and ecosystem tooling than uv.

---

### Decision 2: Just as task runner

**Approach**: [just](https://just.systems/) is used as the single entrypoint for all developer and CI operations. Every meaningful action — running tests, building extensions, releasing, linting, bumping versions — is a named recipe in the root `Justfile`. CI workflows call `just <recipe>` rather than inlining shell commands directly.

**What the Justfile covers**:

| Recipe group | Examples |
|---|---|
| Testing | `test`, `test-all`, `test-affected`, `test-native`, `test-native-affected` |
| Building native extensions | `build-native-inplace`, `build-all-native-inplace`, `build-native-wheels` |
| Releasing | `release`, `bump`, `pending-releases` |
| Code quality | `lint`, `ruff`, `vermin`, `fix` |
| Workspace maintenance | `set-constraint`, `update-meta` |

Having a single canonical set of named commands means: developers do not need to know the exact `uv run` incantation to run tests; CI workflows stay readable because they invoke high-level names rather than multi-line shell; and the Justfile itself becomes the executable documentation of how the repository is operated.

**Why just** (and not the alternatives):

- *Makefiles*: Make is pervasive but carries significant footguns — silently ignoring errors, implicit rules that activate unexpectedly, and variable expansion behaviour that surprises non-Make experts. It was designed for file-dependency build graphs, not arbitrary task orchestration.
- *Shell scripts*: Scripts under `.monorepo/` handle logic that is genuinely complex (affected-package detection, version bumping, release orchestration), but they are not suitable as a top-level task runner. Shell scripts have no built-in help output, no argument defaulting, and no standard way to discover what operations are available. `just --list` gives an instant overview of every recipe.
- *Taskfile / Invoke / nox*: All viable, but less widely known than Make and without just's advantages over Make. just's recipe syntax is designed specifically for task running — it handles multi-line shell scripts, argument passing, and recipe dependencies cleanly, without Make's file-graph semantics getting in the way.

---

### Decision 3: Why not tox-uv

[tox-uv](https://github.com/tox-dev/tox-uv) replaces tox's environment backend with uv, keeping the `testenv` model while gaining uv's installation speed. It is the obvious candidate for a Python-native task runner in a uv-based project, but it has a deeper structural problem that persists regardless of which backend it uses.

**tox conflates environment management with task running.** Every `testenv` entry simultaneously declares *what environment to create* and *what command to run inside it*. These are distinct concerns: environment management is about *what is available* (which Python version, which packages, resolved to which versions); task running is about *what to do* (which command to execute, with which arguments, in which order). Fusing them means every change to one forces you to reason about the other. It also means the unit of configuration is a (task, environment) pair rather than tasks and environments independently — you cannot reuse an environment definition across tasks without either duplicating it or reaching for tox factors, which are a workaround for the original conflation.

Keeping the concerns separate produces a cleaner model: uv owns environment management declaratively via `pyproject.toml` and `uv.lock`, and just owns task running via Justfile recipes. The boundary between them is explicit — uv decides *what is available*, just decides *what to do with it* — and each can be understood and changed independently.

**Workspace friction.** tox creates one venv per `testenv` entry — so `[testenv:py310-lint]`, `[testenv:py310-test]`, and `[testenv:py311-test]` are three separate venvs, each with a full install. uv, by contrast, keys environments on Python version only: all tasks run under `--python 3.10` share one venv, all tasks under `--python 3.11` share another. In a workspace with 31 packages, tox's task × version granularity means installing the entire workspace repeatedly — once per `testenv` — for venvs that are nearly identical. The only escape is to configure tox to delegate environment setup back to `uv sync`, at which point tox is doing no environment management at all and is just a wrapper around the tool that was already doing the job. And since tox is Python-specific, any non-Python step — a shell script, a Rust compile — must still be wrapped in a passthrough `testenv`.

---

### Decision 4: Why not Pants or Bazel

**The appeal**: Build systems like [Pants](https://www.pantsbuild.org/) and [Bazel](https://bazel.build/) offer exactly what a monorepo needs at scale: a hermetic, reproducible, content-addressed build graph; automatic affected-target detection based on fine-grained file dependencies; and a remote build cache that makes repeated CI runs fast even across branches. Pants in particular has strong Python support and could in principle replace both uv (for environment management) and just (for task orchestration).

**Why neither was adopted**:

- *Complexity of setup and maintenance*. Both systems require significant initial configuration and ongoing maintenance. Pants wraps the entire Python toolchain; adopting it means learning Pants-specific BUILD files, target syntax, plugin configuration, and debugging Pants-layer errors in addition to Python errors. For Bazel, the Python rules (`rules_python`) add another layer. The migration cost — translating 31 `pyproject.toml` files and all CI workflows into the target system's model — is high, and the required Pants/Bazel expertise is not currently present in the team.
- *Diminishing returns at this scale*. Pants and Bazel shine at Google/Meta-scale monorepos with hundreds of packages and multi-language builds. At 31 Python packages, the affected-test detection and CI parallelism we need can be implemented in a few hundred lines of Python (`affected_tests.py`, `resolve_linux_archs.py`) without adopting a full build system. The result is simpler to understand, simpler to debug, and requires no specialised knowledge to maintain.
- *Interaction with PyPI publishing*. Publishing to PyPI still requires standard Python wheels built by standard tools. Pants has a publish plugin, but the packaging pipeline for Rust extensions (cibuildwheel, abi3audit, stable-ABI wheels) does not fit naturally into either system without significant custom rule work. The uv + just + cibuildwheel stack is already exactly what those tools expect.

The trade-off is made explicit: we forgo hermetic build graphs and remote caching in exchange for a setup that every Python developer can read and maintain without dedicated build-engineering knowledge.

---

### Decision 5: The workspace test isolation trade-off

**The limitation**: Running tests with `uv run --all-packages` installs all 31 workspace members into a single shared environment. Any package can therefore successfully `import` a sibling workspace package, even if that import is not backed by a declared dependency in `pyproject.toml`. Tests pass inside the monorepo, but the published package fails when an end-user installs it from PyPI and the undeclared dependency is absent.

This is the **ghost dependency** problem. The workspace test environment is not fully representative of the end-user's installed environment.

**Mitigations in place**:

- *cibuildwheel for native packages* (see testing strategy, Decision 2 Mode B): native packages are also built as real wheels and tested inside an isolated cibuildwheel environment, where only the declared dependencies are installed. This catches ghost dependencies for `dissect.util` and `dissect.fve` before they reach PyPI.
- *Pure-Python packages have no equivalent isolation check*. Ghost dependencies in pure-Python packages are not caught by CI and remain a known gap. The practical risk is low because the internal dependency graph is well-understood and reviewed as part of code review, but it is not mechanically enforced.

**Why accepted**: Eliminating workspace test pollution for 31 packages would require either a separate isolated test environment per package (expensive, slow, and essentially reinventing tox) or adopting a hermetic build system (Decision 3). Neither is justified at the current scale. The gap is documented, mitigated for the highest-risk case (native extensions), and accepted for pure-Python packages.
