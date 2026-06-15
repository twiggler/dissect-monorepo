# /// script
# dependencies = ["tomlkit", "packaging"]
# ///

import sys
from pathlib import Path

import tomlkit
from packaging.requirements import Requirement

# The prefix for your internal packages
PREFIX = "dissect."


def _filter_dependencies(dependencies: list[str]):
    for dep in dependencies:
        req = Requirement(dep)
        if req.name.startswith(PREFIX):
            yield req.name


def patch_pyproject(file_path: Path) -> None:
    print(f"Processing {file_path}...")
    doc = tomlkit.parse(file_path.read_text(encoding="utf-8"))

    # 1. Identify internal dependencies
    internal_deps = set()

    # Check main dependencies
    deps: list[str] = doc.get("project", {}).get("dependencies", [])
    internal_deps.update(_filter_dependencies(deps))

    # Check optional dependencies (extras)
    optional_deps = doc.get("project", {}).get("optional-dependencies", {})
    for group in optional_deps.values():
        internal_deps.update(_filter_dependencies(group))

    if not internal_deps:
        print(f"  [-] No internal '{PREFIX}' dependencies found.")
        return

    # 2. Rebuild [tool.uv.sources]
    # Ensure tool and tool.uv exist
    if "tool" not in doc:
        doc["tool"] = tomlkit.table()
    if "uv" not in doc["tool"]:
        doc["tool"]["uv"] = tomlkit.table()

    # Create or clear the sources table
    sources = tomlkit.table()
    for dep in sorted(internal_deps):
        sources[dep] = {"workspace": True}

    doc["tool"]["uv"]["sources"] = sources
    print(f"  [✓] Added {len(internal_deps)} internal sources to [tool.uv.sources]")

    # 3. Write back with formatting preserved
    file_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def main():
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found.", file=sys.stderr)
        sys.exit(1)

    for toml_path in projects_dir.rglob("pyproject.toml"):
        patch_pyproject(toml_path)


if __name__ == "__main__":
    main()
