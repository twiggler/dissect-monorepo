# /// script
# dependencies = ["packaging", "tomlkit"]
# ///

"""Replace setuptools-scm dynamic versioning with a static version in each project's pyproject.toml.

For each project under projects/:

1. [build-system] requires — entries starting with "setuptools-scm" or "setuptools_scm"
   (e.g. "setuptools_scm[toml]>=6.4.0") are removed.

2. [project] dynamic — the "version" entry is removed.  If the list becomes empty the
   key is deleted entirely.

3. [tool.setuptools_scm] — the table is deleted if present.  If [tool] then contains no
   other keys it is also removed.

4. [project] version — set to the version derived from the namespaced git tag written by
   migrate.sh.  Tags have the form <repo>/<version> (e.g. dissect.apfs/1.2.3); the
   highest version tag is selected.
"""

import subprocess
import sys
from pathlib import Path

import tomlkit
from packaging.version import Version


def get_latest_version(repo_name: str) -> str | None:
    """Return the highest version from namespaced git tags for repo_name, or None."""
    result = subprocess.run(
        ["git", "tag", "--list", f"{repo_name}/*"],
        capture_output=True,
        text=True,
        check=True,
    )
    tags = [t.strip() for t in result.stdout.splitlines() if t.strip()]
    if not tags:
        return None

    prefix = f"{repo_name}/"
    latest = sorted(tags, key=lambda t: Version(t[len(prefix) :]))[-1]
    return latest[len(prefix) :]


def decouple_version(file_path: Path, version: str) -> bool:
    doc = tomlkit.parse(file_path.read_text(encoding="utf-8"))

    changed = False
    changed |= _fix_build_system_requires(doc)
    changed |= _fix_dynamic(doc)
    changed |= _fix_setuptools_scm_table(doc)
    changed |= _set_version(doc, version)

    if changed:
        file_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changed


def _fix_build_system_requires(doc: tomlkit.TOMLDocument) -> bool:
    requires = doc.get("build-system", {}).get("requires")
    if requires is None:
        return False

    indices = [i for i, r in enumerate(requires) if str(r).startswith(("setuptools-scm", "setuptools_scm"))]
    if not indices:
        return False

    for i in reversed(indices):
        requires.pop(i)
    print("  [~] build-system.requires: removed setuptools_scm")
    return True


def _fix_dynamic(doc: tomlkit.TOMLDocument) -> bool:
    dynamic = doc.get("project", {}).get("dynamic")
    if dynamic is None:
        return False

    indices = [i for i, v in enumerate(dynamic) if v == "version"]
    if not indices:
        return False

    for i in reversed(indices):
        dynamic.pop(i)

    if len(dynamic) == 0:
        del doc["project"]["dynamic"]
        print("  [~] project.dynamic: removed 'version', key deleted")
    else:
        print("  [~] project.dynamic: removed 'version'")
    return True


def _fix_setuptools_scm_table(doc: tomlkit.TOMLDocument) -> bool:
    if "tool" not in doc or "setuptools_scm" not in doc["tool"]:
        return False

    del doc["tool"]["setuptools_scm"]
    print("  [~] tool.setuptools_scm: removed")

    if len(doc["tool"]) == 0:
        del doc["tool"]
        print("  [~] tool: removed (was empty)")
    return True


def _set_version(doc: tomlkit.TOMLDocument, version: str) -> bool:
    current = doc.get("project", {}).get("version")
    if current == version:
        return False

    doc["project"]["version"] = version
    print(f"  [~] project.version: {current!r} → {version!r}")
    return True


def main() -> None:
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found. Run from the monorepo root.", file=sys.stderr)
        sys.exit(1)

    print("Deriving versions from namespaced git tags...")

    for toml_path in sorted(projects_dir.glob("*/pyproject.toml")):
        repo_name = toml_path.parent.name
        print(f"Processing {repo_name}...")

        version = get_latest_version(repo_name)
        if version is None:
            print(f"  [✗] No namespaced tag found for {repo_name}. Run migrate.sh first.", file=sys.stderr)
            sys.exit(1)

        print(f"  [✓] {repo_name} is at version {version}")
        decouple_version(toml_path, version)


if __name__ == "__main__":
    main()
