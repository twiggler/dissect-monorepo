#!/usr/bin/env python3
"""
Given a list of changed file paths on stdin (one per line, e.g. from
`git diff --name-only`), print the names of all workspace packages that are
affected — i.e. directly changed or transitively depend on a changed package.

Prints one package name per line to stdout.

Usage:
    git diff --name-only origin/master | uv run --group dev python .monorepo/affected_tests.py
"""

import sys
from pathlib import Path

import tomllib
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

WORKSPACE_ROOT = Path(__file__).parent.parent
PROJECTS_DIR = WORKSPACE_ROOT / "projects"


def load_workspace_packages() -> dict[str, tuple[str, Path]]:
    """Return {normalized_name: (original_name, project_dir)} for every package under projects/."""
    packages: dict[str, tuple[str, Path]] = {}
    for pkg_dir in sorted(PROJECTS_DIR.iterdir()):
        pyproject = pkg_dir / "pyproject.toml"
        if not pyproject.is_file():
            continue
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
        name = data.get("project", {}).get("name", "")
        if name:
            packages[canonicalize_name(name)] = (name, pkg_dir)
    return packages


def build_reverse_graph(workspace: dict[str, tuple[str, Path]]) -> dict[str, set[str]]:
    """Return reverse[pkg] = set of workspace packages that directly depend on pkg."""
    reverse: dict[str, set[str]] = {name: set() for name in workspace}

    for name, (_, pkg_dir) in workspace.items():
        with open(pkg_dir / "pyproject.toml", "rb") as fh:
            data = tomllib.load(fh)

        project = data.get("project", {})
        raw_deps: list[str] = list(project.get("dependencies", []))

        for reqs in project.get("optional-dependencies", {}).values():
            raw_deps.extend(reqs)
        # dependency-groups can contain dicts like {include-group=...}, skip those
        for reqs in data.get("dependency-groups", {}).values():
            raw_deps.extend(r for r in reqs if isinstance(r, str))

        for raw in raw_deps:
            try:
                dep_name = canonicalize_name(Requirement(raw).name)
            except InvalidRequirement:
                continue
            if dep_name in workspace and dep_name != name:
                reverse[dep_name].add(name)

    return reverse


def transitive_dependents(changed: set[str], reverse: dict[str, set[str]]) -> set[str]:
    """Return `changed` plus every package that transitively depends on any of them."""
    affected = set(changed)
    queue = list(changed)
    while queue:
        pkg = queue.pop()
        for dep in reverse.get(pkg, set()):
            if dep not in affected:
                affected.add(dep)
                queue.append(dep)
    return affected


def packages_from_changed_files(lines: list[str], workspace: dict[str, tuple[str, Path]]) -> set[str]:
    changed: set[str] = set()
    for line in lines:
        path = WORKSPACE_ROOT / line.strip()
        for name, (_, pkg_dir) in workspace.items():
            try:
                path.relative_to(pkg_dir)
                changed.add(name)
                break
            except ValueError:
                continue
    return changed


def main() -> None:
    changed_files = sys.stdin.read().splitlines()

    workspace = load_workspace_packages()
    reverse = build_reverse_graph(workspace)

    directly_changed = packages_from_changed_files(changed_files, workspace)
    affected = transitive_dependents(directly_changed, reverse)

    for name in sorted(affected & set(workspace)):
        original_name, _ = workspace[name]
        print(original_name)


if __name__ == "__main__":
    main()
