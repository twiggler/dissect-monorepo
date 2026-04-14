#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "packaging",
#   "tomlkit",
# ]
# ///
"""
Bump the minor version of the given workspace packages.

Usage:
    uv run .monorepo/bump_version.py <package> [<package> ...]

Expects explicit package names — validation (double-bump guard) is handled
by the caller (bump.sh).
"""

import sys
from pathlib import Path

import tomlkit
from packaging.utils import canonicalize_name
from packaging.version import Version


def _read_workspace_packages() -> dict[str, tuple[Path, str, str]]:
    """Return {canonical_name: (project_dir, name, version)} for every workspace member."""
    result = {}
    for toml_path in sorted(Path("projects").glob("*/pyproject.toml")):
        if "template" in toml_path.parts:
            continue
        doc = tomlkit.parse(toml_path.read_text())
        project = doc.get("project", {})
        name = project.get("name")
        version = project.get("version")
        if name and version:
            result[canonicalize_name(name)] = (toml_path.parent, name, version)
    return result


def _bump_minor(version: str) -> str:
    # Always emit a 3-part version (major.minor.0), normalizing inputs like "3.4".
    v = Version(version)
    return f"{v.major}.{v.minor + 1}.0"


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("error: no packages specified", file=sys.stderr)
        sys.exit(1)

    workspace = _read_workspace_packages()

    unknown = [name for name in args if canonicalize_name(name) not in workspace]
    if unknown:
        for name in unknown:
            print(f"error: unknown package {name!r}", file=sys.stderr)
        sys.exit(1)

    for name in args:
        project_dir, declared_name, version = workspace[canonicalize_name(name)]
        toml_path = project_dir / "pyproject.toml"
        doc = tomlkit.parse(toml_path.read_text())
        new_version = _bump_minor(version)
        doc["project"]["version"] = new_version
        toml_path.write_text(tomlkit.dumps(doc))
        print(f"  {declared_name}: {version} → {new_version}")

    print(f"\nBumped {len(args)} package(s).")


if __name__ == "__main__":
    main()
