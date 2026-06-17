#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "packaging",
#   "tomlkit",
# ]
# ///
"""Manage versions for workspace packages.

Subcommands:
    bump (auto | <package>...)
        Bump the minor version of the given packages.
        'auto' bumps every package that both has a release tag for its current
        version AND has new commits in its project directory since that tag;
        pending packages (no release tag) are silently skipped.
        Refuses to bump any explicitly named package whose current version has
        no release tag — release pending packages first to avoid double-bumps.
        Refuses to bump any explicitly named package that has no new commits
        since its last release tag — there is nothing to release.

    pending-releases [--names]
        List packages whose current version has no matching git release tag
        (<name>/<version>). With --names, print only package names, one per line.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import tomlkit
from packaging.utils import canonicalize_name
from packaging.version import Version


def _read_workspace_packages() -> dict[str, tuple[Path, str, str]]:
    """Return {canonical_name: (project_dir, declared_name, version)} for every workspace member."""
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
    """Increment the minor component and return a 2-part version (major.minor)."""
    v = Version(version)
    return f"{v.major}.{v.minor + 1}"


def _tag_exists(tag: str) -> bool:
    """Return True if the given git tag exists in the current repository."""
    result = subprocess.run(
        ["git", "tag", "--list", tag],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def _find_release_tag(name: str, version: str) -> str | None:
    """Return the existing release tag for (name, version), or None if no tag exists.

    When the patch component is zero, both the short form (M.m) and the long form
    (M.m.0) are tried so that tags created under either convention are recognised.
    Returns the matching tag string so callers can use it directly as a git ref.
    """
    primary = f"{name}/{version}"
    if _tag_exists(primary):
        return primary

    v = Version(version)
    if v.micro == 0:
        alt_ver = f"{v.major}.{v.minor}.0" if len(v.release) == 2 else f"{v.major}.{v.minor}"
        alt = f"{name}/{alt_ver}"
        if _tag_exists(alt):
            return alt

    return None


def _has_commits_since_tag(name: str, version: str, project_dir: Path) -> bool:
    """Return True if there are commits touching project_dir since the release tag.

    Two independent windows are checked to avoid the migration range masking
    pre-migration work:

      1. Post-migration: commits after migration/end that are not yet released.
      2. Pre-migration: commits in the project's imported history that arrived
         via its merge commit (migration/start/<name>) but weren't yet released.
    """
    release_tag = _find_release_tag(name, version) or f"{name}/{version}"

    # 1. Post-migration: new work after the migration window that hasn't been released.
    post_cmd = [
        "git",
        "log",
        "--oneline",
        f"^{release_tag}",
        "^migration/end",
        "HEAD",
        "--",
        str(project_dir),
    ]
    if subprocess.run(post_cmd, capture_output=True, text=True, check=True).stdout.strip():
        return True

    # 2. Pre-migration: unreleased work that was in the project's history when
    #    it was merged into the monorepo.
    pre_cmd = [
        "git",
        "log",
        "--oneline",
        f"^{release_tag}",
        f"migration/start/{name}",
        "--",
        str(project_dir),
    ]
    return bool(subprocess.run(pre_cmd, capture_output=True, text=True, check=True).stdout.strip())


def cmd_pending_releases(args: argparse.Namespace) -> int:
    workspace = _read_workspace_packages()
    pending = []
    not_pending = []
    for _, name, version in sorted(workspace.values(), key=lambda e: e[1]):
        if _find_release_tag(name, version) is not None:
            not_pending.append((name, version))
        else:
            pending.append((name, version))

    if args.names:
        for name, _ in pending:
            print(name)
    else:
        col = 30
        for name, version in pending:
            print(f"{name:<{col}} {version:<12}  no tag (pending)")
        for name, version in not_pending:
            print(f"{name:<{col}} {version:<12}  tagged")
    return 0


def _resolve_auto_targets(workspace: dict[str, tuple[Path, str, str]]) -> list[str] | int:
    """Return the list of packages to bump automatically, or an int exit code."""
    to_bump = []
    skipped_pending = []

    for project_dir, name, version in sorted(workspace.values(), key=lambda e: e[1]):
        if _find_release_tag(name, version) is None:
            skipped_pending.append(name)
            continue
        if not _has_commits_since_tag(name, version, project_dir):
            continue
        to_bump.append(name)

    if skipped_pending:
        print(f"[skip] {len(skipped_pending)} package(s) already bumped and awaiting release:")
        for name in skipped_pending:
            print(f"  {name}")

    if not to_bump:
        print("Nothing to auto-bump.")
        return 0

    return to_bump


def _resolve_explicit_targets(workspace: dict[str, tuple[Path, str, str]], packages: list[str]) -> list[str] | int:
    """Validate and return the explicitly requested packages to bump, or an int exit code."""
    unknown = [name for name in packages if canonicalize_name(name) not in workspace]
    if unknown:
        for name in unknown:
            print(f"error: unknown package {name!r}", file=sys.stderr)
        return 1

    double_bumps = [name for name in packages if _find_release_tag(name, workspace[canonicalize_name(name)][2]) is None]
    if double_bumps:
        print("error: the following packages have no release tag for their current version.", file=sys.stderr)
        print("Release them first, or create the tags manually.", file=sys.stderr)
        print(file=sys.stderr)
        for name in double_bumps:
            print(f"  {name}", file=sys.stderr)
        return 1

    no_new_commits = [
        name
        for name in packages
        for project_dir, _, version in (workspace[canonicalize_name(name)],)
        if not _has_commits_since_tag(name, version, project_dir)
    ]
    if no_new_commits:
        print("error: the following packages have no new commits since their last release tag.", file=sys.stderr)
        print("Nothing to release — bump is not needed.", file=sys.stderr)
        print(file=sys.stderr)
        for name in no_new_commits:
            print(f"  {name}", file=sys.stderr)
        return 1

    return packages


def _apply_bumps(workspace: dict[str, tuple[Path, str, str]], targets: list[str]) -> int:
    """Write bumped versions to disk and report. Returns 0."""
    for name in targets:
        project_dir, declared_name, version = workspace[canonicalize_name(name)]
        toml_path = project_dir / "pyproject.toml"
        doc = tomlkit.parse(toml_path.read_text())
        new_version = _bump_minor(version)
        doc["project"]["version"] = new_version
        toml_path.write_text(tomlkit.dumps(doc))
        print(f"  {declared_name}: {version} → {new_version}")

    print(f"\nBumped {len(targets)} package(s).")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    workspace = _read_workspace_packages()

    if args.packages == ["auto"]:
        result = _resolve_auto_targets(workspace)
    else:
        result = _resolve_explicit_targets(workspace, args.packages)

    if isinstance(result, int):
        return result

    return _apply_bumps(workspace, result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending_parser = subparsers.add_parser(
        "pending-releases",
        help="List packages whose current version has no release tag.",
    )
    pending_parser.add_argument(
        "--names",
        action="store_true",
        help="Print only package names, one per line.",
    )

    bump_parser = subparsers.add_parser(
        "bump",
        help="Bump the minor version of workspace packages.",
    )
    bump_parser.add_argument(
        "packages",
        nargs="+",
        metavar="package",
        help=("Package names, or 'auto' to bump packages with new commits since their last release tag."),
    )

    args = parser.parse_args()
    if args.command == "pending-releases":
        sys.exit(cmd_pending_releases(args))
    elif args.command == "bump":
        sys.exit(cmd_bump(args))


if __name__ == "__main__":
    main()
