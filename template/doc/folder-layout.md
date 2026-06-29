# Plan: Dissect Monorepo — Folder Layout

### Background

When 31 individual `dissect.*` repositories were merged into a single uv workspace, every file had to land somewhere predictable. The layout described here is the result of that migration: a small set of top-level files that configure the whole workspace, a `projects/` directory that contains every package, and a handful of hidden directories (`/.monorepo`, `/.github`) that hold CI tooling. Understanding it once makes every other part of the repository — tooling, CI, release mechanics — easier to navigate.

---

### Top-level files

```
/
├── pyproject.toml          # Workspace root: uv workspace declaration, shared tool config
├── uv.lock                 # Single lockfile for all 31 packages and their dependencies
├── Justfile                # All developer and CI commands (see tooling.md)
├── ruff.toml               # Shared ruff configuration, inherited by all packages
└── projects/               # Every dissect.* package — one subdirectory each
```

**`pyproject.toml`** is the workspace root but is not itself a publishable package — it has no importable source and is not listed on PyPI. Its roles are:

- `[tool.uv.workspace]` — declares `projects/*` as workspace members so uv resolves them together.
- `[tool.uv.sources]` — wires every `dissect.*` dependency to its local workspace copy during development.
- `[tool.monorepo.test]` — records the `python-versions` and `os` matrix used by CI to generate the test job matrix.
- `[tool.monorepo.native]` — records the architecture lists for the native wheel build (`linux-x86-archs-pr`, `linux-x86-archs`).
- `[tool.cibuildwheel]` — shared cibuildwheel configuration (stable ABI, platform overrides, test command) used by all native packages.

**`uv.lock`** is generated and maintained by uv. It is committed to version control so that every developer and every CI runner gets an identical environment from `uv sync`. It must not be edited by hand; `uv lock` regenerates it whenever `pyproject.toml` changes in any workspace member.

**`ruff.toml`** contains formatting and lint rules that apply workspace-wide. Individual packages do not carry their own ruff configuration.

---

### The `projects/` directory

Each `dissect.*` package lives under `projects/<package-name>/`. The name matches the PyPI distribution name exactly (e.g. `projects/dissect.cstruct`, `projects/dissect.util`). All 31 packages use the same internal layout:

```
projects/<package>/
├── pyproject.toml          # Package metadata, version, dependencies, build config
├── src/
│   └── dissect/
│       └── <module>/       # Package source code (PEP 420 implicit namespace package)
├── tests/                  # pytest test suite for this package
├── COPYRIGHT
├── LICENSE
├── README.md
├── CHANGELOG.md            # (most packages)
├── MANIFEST.in
```

**`src/` layout**: all packages follow the standard `src/` layout — source lives under `src/dissect/<module>/` rather than directly at `projects/<package>/dissect/<module>/`. This keeps the package root off `sys.path` by default, which prevents accidentally importing source files without a proper install or editable install.

**Implicit namespace package**: the `dissect` directory under `src/` contains no `__init__.py`. All `dissect.*` packages share the `dissect` namespace via PEP 420 implicit namespace packages. uv's editable installs and the workspace `PYTHONPATH` wire them together at development time without any special coordination between packages.

**`pyproject.toml` per package**: each package carries its own `pyproject.toml` with its own `[project]` table (name, version, dependencies). The version field is the authoritative source of the package's current version — there are no git-tag-derived dynamic versions. Dependencies on other `dissect.*` packages are declared here with version bounds; `[tool.uv.sources]` in the root `pyproject.toml` then overrides those bounds to point at the local workspace copy during development.

---

### Native packages

Two packages — `dissect.util` and `dissect.fve` — contain a Rust extension. Their layout adds a Rust source tree alongside the Python source:

```
projects/dissect.util/
├── pyproject.toml          # build-backend points to a custom _build.py (see below)
├── src/
│   └── dissect/
│       └── util/
│           ├── _build.py           # Custom build backend: drives Rust compilation
│           ├── _native/            # Stub package: .pyi type stubs for the Rust extension
│           │   ├── __init__.pyi
│           │   ├── compression/
│           │   └── hash/
│           └── _native.src/        # Rust extension source
│               ├── Cargo.toml
│               ├── Cargo.lock
│               └── src/            # Rust source files
├── tests/
└── ...
```

**`_build.py`**: a custom PEP 517 build backend stored inside the package source tree. It delegates to setuptools for the Python packaging mechanics but intercepts the wheel-build step to compile the Rust extension via `setuptools-rust`. This is what `pyproject.toml`'s `backend-path = ["src/dissect/util"]` and `build-backend = "_build"` refer to.

**`_native/`**: contains Python type stubs (`.pyi` files) that describe the public API of the compiled Rust extension. At import time the runtime picks up the compiled `.so`/`.pyd` in place of these stubs; the stubs exist solely for static type checking and IDE completion.

**`_native.src/`**: the Rust crate. `Cargo.toml` declares the crate and its Rust dependencies; `Cargo.lock` pins them. The `src/` subdirectory follows the standard Rust `src/lib.rs` layout.
