# /// script
# dependencies = ["tomlkit"]
# ///

"""Fix [build-system] backend-path entries that don't account for a src/ layout.

For projects using a custom local build backend (build-backend = "_build"),
the backend-path must point to the directory that actually contains _build.py.
In a src/ layout the correct path is e.g. "src/dissect/util" rather than
"dissect/util".  This script detects the mismatch and corrects it.
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

    build_system = doc.get("build-system", {})
    backend_path = build_system.get("backend-path")
    build_backend = build_system.get("build-backend")

    if not backend_path or not build_backend:
        print("  [-] No backend-path / build-backend found, skipping.")
        return

    # Only relevant for local (non-dotted) backends like "_build"
    if "." in build_backend:
        print(f"  [-] build-backend '{build_backend}' looks like a PyPI package, skipping.")
        return

    actual_dir = _find_build_py(project_root, build_backend)
    if actual_dir is None:
        print(f"  [!] Could not find '{build_backend}.py' anywhere under {project_root}, skipping.")
        return

    correct_path = str(actual_dir.relative_to(project_root))

    if backend_path == [correct_path]:
        print(f"  [✓] backend-path already correct: {backend_path}")
        return

    print(f"  [~] Fixing backend-path: {backend_path} → ['{correct_path}']")
    doc["build-system"]["backend-path"] = [correct_path]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))
    print(f"  [✓] Updated {file_path}")


def main() -> None:
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found.")
        return

    for toml_path in sorted(projects_dir.rglob("pyproject.toml")):
        patch_pyproject(toml_path)


if __name__ == "__main__":
    main()
