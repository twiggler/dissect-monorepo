#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "packaging",
#   "tomlkit",
# ]
# ///
"""
Update the version specifier for an internal dependency across all workspace projects.

Only modifies projects that already declare the dependency — in either
[project.dependencies] or any [project.optional-dependencies] group.
Uses tomlkit for lossless round-tripping (preserves comments, formatting, ordering).

Why not `uv add`?
  - `uv add` always adds the dependency if it is absent, which would silently
    introduce new dependencies in projects that don't need them.
  - `uv add` only targets [project.dependencies]; updating optional-dependency
    groups would require a separate `uv add --optional <group>` call per group
    per project — far more invocations for no benefit.
  - Each `uv add` call re-resolves and rewrites the lockfile. Doing this once
    per project (×28) is significantly slower than editing all pyproject.toml
    files in one pass and running `uv lock` once afterward.

Usage:
    uv run .monorepo/set_constraint.py dissect.cstruct ">=4.7,<5"
"""

import argparse
import sys
from pathlib import Path

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def _replace_specifier(req_str: str, target: str, new_specifier: str) -> str | None:
    """
    If req_str refers to target (by normalized name), return a new requirement
    string with the specifier replaced. Returns None if the name doesn't match.
    Preserves extras and environment markers from the original.
    """
    try:
        req = Requirement(req_str)
    except Exception:
        return None

    if canonicalize_name(req.name) != canonicalize_name(target):
        return None

    name_part = req.name
    if req.extras:
        name_part += f"[{','.join(sorted(req.extras))}]"

    result = f"{name_part}{new_specifier}"
    if req.marker:
        result += f" ; {req.marker}"
    return result


def _update_dep_list(dep_list, target: str, new_specifier: str) -> int:
    """Mutate a tomlkit array in-place. Returns the number of replacements made."""
    count = 0
    for i, item in enumerate(dep_list):
        replacement = _replace_specifier(str(item), target, new_specifier)
        if replacement is not None:
            dep_list[i] = replacement
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update a dependency's version specifier across all workspace projects."
    )
    parser.add_argument("package", help="Package name to update (e.g. dissect.cstruct)")
    parser.add_argument("specifier", help="New version specifier (e.g. '>=4.7,<5')")
    args = parser.parse_args()

    projects_dir = Path("projects")
    if not projects_dir.is_dir():
        print(
            "Error: must be run from the monorepo root ('projects/' directory not found)",
            file=sys.stderr,
        )
        sys.exit(1)

    modified = []
    for pkg_dir in sorted(projects_dir.iterdir()):
        pp = pkg_dir / "pyproject.toml"
        if not pp.is_file():
            continue

        doc = tomlkit.parse(pp.read_text())
        project = doc.get("project", {})
        count = 0

        deps = project.get("dependencies")
        if deps is not None:
            count += _update_dep_list(deps, args.package, args.specifier)

        for group_deps in project.get("optional-dependencies", {}).values():
            count += _update_dep_list(group_deps, args.package, args.specifier)

        if count:
            pp.write_text(tomlkit.dumps(doc))
            modified.append((pkg_dir.name, count))

    if modified:
        for name, n in modified:
            print(f"  {name}: updated {n} occurrence(s)")
    else:
        print(f"No projects declare a dependency on {args.package!r}.")


if __name__ == "__main__":
    main()
