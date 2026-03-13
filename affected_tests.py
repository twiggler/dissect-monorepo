#!/usr/bin/env python3
"""
Affected test runner for the dissect monorepo.

Runs pytest only for packages whose source (or any transitive workspace
dependency's source) has changed since the last successful run.

Cache key per package = SHA-256 of (own src/**/*.py + pyproject.toml)
                       + (same recursively for all transitive workspace deps)
                       + python version

This means changing dissect.util automatically invalidates the cache of every
package that (transitively) depends on it, even if that package's own files
didn't change.

Usage:
    # Run all packages, using cache to skip unchanged ones:
    python scripts/affected_tests.py --python 3.10

    # Same, but also prune packages not downstream of any git-changed file:
    python scripts/affected_tests.py --python 3.10 --affected origin/master

    # Ignore cache, re-run everything:
    python scripts/affected_tests.py --python 3.10 --no-cache
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-reattr]
        except ImportError:
            sys.exit("Python < 3.11 requires 'tomli': uv pip install tomli")

WORKSPACE_ROOT = Path(__file__).parent.parent
PROJECTS_DIR = WORKSPACE_ROOT / "projects"
CACHE_DIR = WORKSPACE_ROOT / ".test-cache"


# ---------------------------------------------------------------------------
# Workspace discovery
# ---------------------------------------------------------------------------

def load_workspace_packages() -> dict[str, Path]:
    """Return {normalized_name: project_dir} for every package under projects/."""
    packages: dict[str, Path] = {}
    for pkg_dir in sorted(PROJECTS_DIR.iterdir()):
        pyproject = pkg_dir / "pyproject.toml"
        if not pyproject.is_file():
            continue
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
        name = data.get("project", {}).get("name", "")
        if name:
            packages[canonicalize_name(name)] = pkg_dir
    return packages


# ---------------------------------------------------------------------------
# Dependency graph (from pyproject.toml, workspace packages only)
# ---------------------------------------------------------------------------

def build_dep_graphs(
    workspace: dict[str, Path],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """
    Returns (forward, reverse):
      forward[pkg]  = set of workspace packages that pkg directly depends on
      reverse[pkg]  = set of workspace packages that directly depend on pkg
    """
    forward: dict[str, set[str]] = {name: set() for name in workspace}
    reverse: dict[str, set[str]] = {name: set() for name in workspace}

    for name, pkg_dir in workspace.items():
        with open(pkg_dir / "pyproject.toml", "rb") as fh:
            data = tomllib.load(fh)

        project = data.get("project", {})
        raw_deps: list[str] = list(project.get("dependencies", []))

        # also include optional-dependencies and dependency-groups
        # (dependency-groups can contain dicts like {include-group=...}, skip those)
        for reqs in project.get("optional-dependencies", {}).values():
            raw_deps.extend(reqs)
        for reqs in data.get("dependency-groups", {}).values():
            raw_deps.extend(r for r in reqs if isinstance(r, str))

        for raw in raw_deps:
            try:
                dep_name = canonicalize_name(Requirement(raw).name)
            except InvalidRequirement:
                continue
            if dep_name in workspace and dep_name != name:
                forward[name].add(dep_name)
                reverse[dep_name].add(name)

    return forward, reverse


def transitive_deps(name: str, forward: dict[str, set[str]]) -> set[str]:
    """Return all transitive workspace dependencies of `name` (not including itself)."""
    visited: set[str] = set()
    queue = list(forward.get(name, set()))
    while queue:
        dep = queue.pop()
        if dep not in visited:
            visited.add(dep)
            queue.extend(forward.get(dep, set()))
    return visited


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


# ---------------------------------------------------------------------------
# Cache key computation
# ---------------------------------------------------------------------------

def hash_package_sources(pkg_dir: Path) -> bytes:
    """SHA-256 digest of src/**/*.py + pyproject.toml in a package directory."""
    h = hashlib.sha256()
    files = sorted(
        list(pkg_dir.glob("src/**/*.py")) + [pkg_dir / "pyproject.toml"]
    )
    for f in files:
        if f.is_file():
            # include relative path so renames are detected
            h.update(str(f.relative_to(pkg_dir)).encode())
            h.update(f.read_bytes())
    return h.digest()


def compute_cache_key(
    name: str,
    workspace: dict[str, Path],
    forward: dict[str, set[str]],
    python_version: str,
) -> str:
    h = hashlib.sha256()
    # own sources + all transitive dep sources, in stable order
    all_relevant = sorted({name} | transitive_deps(name, forward))
    for dep in all_relevant:
        h.update(dep.encode())
        h.update(hash_package_sources(workspace[dep]))
    h.update(python_version.encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Git-based affected set (optional pre-filter)
# ---------------------------------------------------------------------------

def git_changed_packages(base_ref: str, workspace: dict[str, Path]) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        path = WORKSPACE_ROOT / line
        for name, pkg_dir in workspace.items():
            try:
                path.relative_to(pkg_dir)
                changed.add(name)
                break
            except ValueError:
                continue
    return changed


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(pkg_dir: Path, python_version: str) -> bool:
    result = subprocess.run(
        [
            "uv", "run",
            "--group", "dev",
            "--all-packages",
            "--all-extras",
            "--python", python_version,
            "pytest", str(pkg_dir),
        ],
        cwd=WORKSPACE_ROOT,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", default="3.10", metavar="VERSION", help="Python version to test with (default: 3.10)")
    parser.add_argument("--affected", metavar="REF", help="Only test packages downstream of files changed vs REF (e.g. origin/master)")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached results and re-run everything")
    parser.add_argument("packages", nargs="*", help="Specific packages to test (default: all)")
    args = parser.parse_args()

    CACHE_DIR.mkdir(exist_ok=True)

    workspace = load_workspace_packages()
    forward, reverse = build_dep_graphs(workspace)

    # Determine which packages to consider
    if args.packages:
        candidates = {canonicalize_name(p) for p in args.packages}
        unknown = candidates - set(workspace)
        if unknown:
            sys.exit(f"Unknown packages: {', '.join(sorted(unknown))}")
    elif args.affected:
        changed = git_changed_packages(args.affected, workspace)
        if not changed:
            print("No workspace packages affected by changes. Nothing to do.")
            return
        candidates = transitive_dependents(changed, reverse)
    else:
        candidates = set(workspace)

    # Sort alphabetically for consistent, readable output
    to_run = sorted(candidates & set(workspace))

    print(f"Packages to test ({len(to_run)}): {', '.join(to_run)}\n")

    passed: list[str] = []
    cached: list[str] = []
    failed: list[str] = []

    for name in to_run:
        pkg_dir = workspace[name]
        cache_key = compute_cache_key(name, workspace, forward, args.python)
        cache_file = CACHE_DIR / f"{name}--py{args.python.replace('.', '')}--{cache_key[:24]}.ok"

        if not args.no_cache and cache_file.exists():
            print(f"  [cached]  {name}")
            cached.append(name)
            continue

        # Remove stale cache entries for this package+python combo
        for stale in CACHE_DIR.glob(f"{name}--py{args.python.replace('.', '')}--*.ok"):
            stale.unlink()

        print(f"  [running] {name}")
        if run_tests(pkg_dir, args.python):
            cache_file.touch()
            passed.append(name)
        else:
            failed.append(name)

    print(f"\n{'─' * 50}")
    print(f"  Passed:  {len(passed)}")
    print(f"  Cached:  {len(cached)}")
    print(f"  Failed:  {len(failed)}")
    if failed:
        print(f"\n  FAILED: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
