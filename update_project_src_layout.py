# /// script
# dependencies = ["tomlkit"]
# ///

"""Update pyproject.toml files in projects/ for a correct src/ layout.

Fixes are applied to every project:

1. [build-system] requires — setuptools_scm is removed. All dissect
   packages declare a static version in [project], so setuptools_scm is
   never needed and only causes spurious git subprocess calls at build time.

2. [build-system] backend-path — For projects using a custom local build
   backend (build-backend = "_build"), the backend-path must point to the
   directory that contains _build.py.  In a src/ layout the correct value is
   e.g. "src/dissect/util" rather than "dissect/util".

3. [tool.setuptools.packages.find] where — Without `where = ["src"]`,
   setuptools scans the project root and finds nothing, resulting in an empty
   editable-install finder.  This fix adds the missing directive so that
   packages installed in editable mode are discoverable at import time.

4. [tool.pytest.ini_options] — pytest determines rootdir by walking upward
   from the test paths looking for a config file.  Without this table,
   pytest anchors rootdir to the monorepo root rather than the project
   directory, breaking tests that rely on rootdir (e.g. LFS tracking tests).
   Adding an empty table with `testpaths = ["tests"]` anchors rootdir to
   the project directory.

Project-specific fixes:

- dissect.fve: adds an `argon2` optional extra with `argon2-cffi` so that
  the Argon2 password-hashing fallback works without building the native
  Rust extension.  This mirrors the `argon2-cffi` entry that was in tox.ini.
"""

import tomlkit
from pathlib import Path


def _find_build_py(project_root: Path, module: str) -> Path | None:
    """Return the directory that contains <module>.py, searching under project_root."""
    for candidate in project_root.rglob(f"{module}.py"):
        return candidate.parent
    return None


def patch_pyproject(file_path: Path) -> None:
    print(f"Processing {file_path}...")
    project_root = file_path.parent

    with open(file_path, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())

    changed = False
    changed |= _fix_build_system_requires(doc)
    changed |= _fix_backend_path(doc, project_root)
    changed |= _fix_packages_find_where(doc, project_root)
    changed |= _fix_pytest_ini_options(doc, project_root)
    changed |= _fix_fve_argon2_extra(doc, project_root)

    if changed:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        print(f"  [✓] Updated {file_path}")


def _fix_build_system_requires(doc: tomlkit.TOMLDocument) -> bool:
    """Remove setuptools_scm from build-system.requires."""
    requires = doc.get("build-system", {}).get("requires")
    if requires is None:
        print("  [-] build-system.requires: no build-system found, skipping.")
        return False

    indices = [i for i, r in enumerate(requires) if str(r).startswith("setuptools_scm")]
    if not indices:
        print("  [-] build-system.requires: setuptools_scm not present, skipping.")
        return False

    for i in reversed(indices):
        requires.pop(i)
    print("  [~] build-system.requires: removed setuptools_scm")
    return True


def _fix_backend_path(doc: tomlkit.TOMLDocument, project_root: Path) -> bool:
    build_system = doc.get("build-system", {})
    backend_path = build_system.get("backend-path")
    build_backend = build_system.get("build-backend")

    if not backend_path or not build_backend:
        print("  [-] backend-path: no backend-path / build-backend found, skipping.")
        return False

    # Only relevant for local (non-dotted) backends like "_build"
    if "." in build_backend:
        print(f"  [-] backend-path: '{build_backend}' looks like a PyPI package, skipping.")
        return False

    actual_dir = _find_build_py(project_root, build_backend)
    if actual_dir is None:
        print(f"  [!] backend-path: could not find '{build_backend}.py' under {project_root}, skipping.")
        return False

    correct_path = str(actual_dir.relative_to(project_root))

    if backend_path == [correct_path]:
        print(f"  [✓] backend-path already correct: {backend_path}")
        return False

    print(f"  [~] backend-path: {backend_path} → ['{correct_path}']")
    doc["build-system"]["backend-path"] = [correct_path]
    return True


def _fix_packages_find_where(doc: tomlkit.TOMLDocument, project_root: Path) -> bool:
    """Ensure [tool.setuptools.packages.find] has where = ["src"] for src layouts."""
    src_dir = project_root / "src"
    if not src_dir.is_dir():
        print("  [-] packages.find where: no src/ directory, skipping.")
        return False

    tool = doc.get("tool", {})
    setuptools = tool.get("setuptools", {})
    packages = setuptools.get("packages", {})
    find = packages.get("find", {})

    current_where = find.get("where")
    if current_where == ["src"]:
        print("  [✓] packages.find where already correct.")
        return False

    # Build the nested structure if any level is missing
    if "tool" not in doc:
        doc.add("tool", tomlkit.table())
    if "setuptools" not in doc["tool"]:
        doc["tool"].add("setuptools", tomlkit.table())
    if "packages" not in doc["tool"]["setuptools"]:
        doc["tool"]["setuptools"].add("packages", tomlkit.table())
    if "find" not in doc["tool"]["setuptools"]["packages"]:
        doc["tool"]["setuptools"]["packages"].add("find", tomlkit.table())

    print(f"  [~] packages.find where: {current_where!r} → ['src']")
    doc["tool"]["setuptools"]["packages"]["find"]["where"] = ["src"]
    return True


def _fix_pytest_ini_options(doc: tomlkit.TOMLDocument, project_root: Path) -> bool:
    """Ensure [tool.pytest.ini_options] exists to anchor pytest rootdir to the project."""
    src_dir = project_root / "src"
    if not src_dir.is_dir():
        print("  [-] pytest.ini_options: no src/ directory, skipping.")
        return False

    tool = doc.get("tool", {})
    pytest_opts = tool.get("pytest", {}).get("ini_options")
    if pytest_opts is not None:
        print("  [✓] pytest.ini_options already present.")
        return False

    if "tool" not in doc:
        doc.add("tool", tomlkit.table())
    if "pytest" not in doc["tool"]:
        doc["tool"].add("pytest", tomlkit.table(is_super_table=True))
    ini_options = tomlkit.table()
    ini_options.add("testpaths", ["tests"])
    doc["tool"]["pytest"].add("ini_options", ini_options)

    print("  [~] pytest.ini_options: added with testpaths = ['tests']")
    return True


def _fix_fve_argon2_extra(doc: tomlkit.TOMLDocument, project_root: Path) -> bool:
    """Add argon2 optional extra to dissect.fve so argon2-cffi is installed via --all-extras.

    dissect.fve has a native Rust Argon2 extension with argon2-cffi as a pure-Python
    fallback.  The fallback was previously listed in tox.ini deps but never declared
    as a project dependency, so it was missing in the uv workspace.  Adding it as an
    optional extra means --all-extras in the Justfile recipe picks it up automatically.
    """
    project_name = doc.get("project", {}).get("name", "")
    if project_name != "dissect.fve":
        return False

    opt_deps = doc.get("project", {}).get("optional-dependencies", {})
    if "argon2" in opt_deps:
        print("  [✓] fve argon2 extra already present.")
        return False

    argon2_array = tomlkit.array()
    argon2_array.append("argon2-cffi")
    doc["project"]["optional-dependencies"]["argon2"] = argon2_array
    print("  [~] fve: added argon2 optional extra with argon2-cffi")
    return True


def main() -> None:
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found.")
        return

    for toml_path in sorted(projects_dir.rglob("pyproject.toml")):
        patch_pyproject(toml_path)


if __name__ == "__main__":
    main()
