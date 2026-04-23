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
    bump (all | <package>...)
        Bump the minor version of the given packages.
        'all' expands to every workspace member.
        Refuses to bump any package whose current version has no release tag —
        release pending packages first to avoid double-bumps.

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
    # Always emit a 3-part version (major.minor.0), normalizing inputs like "3.4".
    v = Version(version)
    return f"{v.major}.{v.minor + 1}.0"


def _has_release_tag(name: str, version: str) -> bool:
    """Return True if a git tag <name>/<version> exists in the current repository."""
    result = subprocess.run(
        ["git", "tag", "--list", f"{name}/{version}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def cmd_pending_releases(args: argparse.Namespace) -> int:
    workspace = _read_workspace_packages()
    pending = []
    not_pending = []
    for _project_dir, name, version in sorted(workspace.values(), key=lambda e: e[1]):
        if _has_release_tag(name, version):
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


def cmd_bump(args: argparse.Namespace) -> int:
    workspace = _read_workspace_packages()

    if args.packages == ["all"]:
        targets = [name for _dir, name, _ver in sorted(workspace.values(), key=lambda e: e[1])]
    else:
        targets = args.packages

    unknown = [name for name in targets if canonicalize_name(name) not in workspace]
    if unknown:
        for name in unknown:
            print(f"error: unknown package {name!r}", file=sys.stderr)
        return 1

    double_bumps = [
        name for name in targets
        if not _has_release_tag(name, workspace[canonicalize_name(name)][2])
    ]
    if double_bumps:
        print("error: the following packages have no release tag for their current version.", file=sys.stderr)
        print("Release them first, or create the tags manually.", file=sys.stderr)
        print(file=sys.stderr)
        for name in double_bumps:
            print(f"  {name}", file=sys.stderr)
        return 1

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
        help="Package names, or 'all' to bump every workspace member.",
    )

    args = parser.parse_args()
    if args.command == "pending-releases":
        sys.exit(cmd_pending_releases(args))
    elif args.command == "bump":
        sys.exit(cmd_bump(args))


if __name__ == "__main__":
    main()
