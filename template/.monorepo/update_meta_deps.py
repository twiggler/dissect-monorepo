#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "packaging",
#   "tomlkit",
# ]
# ///
"""
Regenerate the dependency list of the dissect meta-package.

Iterates over the existing entries in projects/dissect/pyproject.toml
[project.dependencies] and updates the version pin of each entry to match
the current version declared in that package's own pyproject.toml.

Only existing entries are modified — the script never adds or removes
dependencies. Extras (e.g. dissect.target[full]) are preserved.

Usage:
    uv run .monorepo/update_meta_deps.py
"""

from pathlib import Path

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


META_TOML = Path("projects/dissect/pyproject.toml")


def _read_workspace_versions() -> dict[str, str]:
    """Return a map of canonical_name -> version for all workspace members."""
    versions: dict[str, str] = {}
    for toml_path in Path("projects").glob("*/pyproject.toml"):
        if "template" in toml_path.parts:
            continue
        doc = tomlkit.parse(toml_path.read_text())
        name = str(doc["project"]["name"])
        version = str(doc["project"]["version"])
        versions[canonicalize_name(name)] = version
    return versions


def main() -> None:
    workspace_versions = _read_workspace_versions()

    meta_text = META_TOML.read_text()
    meta_doc = tomlkit.parse(meta_text)
    dep_list = meta_doc["project"]["dependencies"]

    updated = 0
    for i, item in enumerate(dep_list):
        try:
            req = Requirement(str(item))
        except Exception:
            continue

        canon = canonicalize_name(req.name)
        version = workspace_versions.get(canon)
        if version is None:
            print(f"  [!] {req.name}: not found in workspace, skipping")
            continue

        extras_str = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
        new_entry = f"{req.name}{extras_str}=={version}"
        if str(item) != new_entry:
            dep_list[i] = new_entry
            updated += 1

    META_TOML.write_text(tomlkit.dumps(meta_doc))
    print(f"Updated {updated} entr{'y' if updated == 1 else 'ies'} in {META_TOML}.")


if __name__ == "__main__":
    main()

