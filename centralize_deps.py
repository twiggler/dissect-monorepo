# /// script
# dependencies = ["tomlkit"]
# ///

"""Remove per-project dev/test tooling that is now owned by the monorepo root.

For each sub-project pyproject.toml:

  [dependency-groups]:
    - The 'test' group, if present and non-empty, is preserved and renamed to
      'dev'. It typically contains package-specific test dependencies (e.g.
      pexpect, docutils) that are not part of the workspace-wide tooling.
      include-group references are dropped since the groups they point to are
      being removed.
    - All other groups (lint, build, debug, dev, ...) are removed. These only
      ever contained tooling now centralised in the root [dependency-groups].
    - If the 'test' group is absent or empty the entire [dependency-groups]
      table is removed.

  [project.optional-dependencies]:
    - The 'dev' extra is removed. It duplicated what is now in the root and has
      no meaning inside the monorepo.
    - All other extras (full, yara, test, ...) are preserved — they are part of
      the package's published PyPI metadata.

The root pyproject.toml is not modified by this script; its [dependency-groups]
are maintained directly.
"""

import tomlkit
from pathlib import Path

PROJECTS_DIR = Path("projects")


def clean_subproject(file_path: Path) -> None:
    with open(file_path, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())

    modified = False

    # --- [dependency-groups] ---
    if "dependency-groups" in doc:
        dep_groups = doc["dependency-groups"]

        # Collect entries from the 'test' group, dropping include-group refs.
        test_entries = [
            e for e in dep_groups.get("test", [])
            if isinstance(e, str)
        ]

        del doc["dependency-groups"]
        modified = True

        if test_entries:
            # Rename 'test' → 'dev' and keep only the real package-specific entries.
            new_groups = tomlkit.table()
            arr = tomlkit.array()
            arr.multiline(True)
            for entry in test_entries:
                arr.append(entry)
            new_groups["dev"] = arr
            doc["dependency-groups"] = new_groups

    # --- [project.optional-dependencies.dev] ---
    opt_deps = doc.get("project", {}).get("optional-dependencies", {})
    if "dev" in opt_deps:
        del opt_deps["dev"]
        modified = True
        if not opt_deps:
            del doc["project"]["optional-dependencies"]

    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        print(f"  [✓] Cleaned {file_path.parent.name}")
    else:
        print(f"  [-] No changes needed for {file_path.parent.name}")


def main():
    print("Cleaning sub-projects...")
    for toml_path in sorted(PROJECTS_DIR.rglob("pyproject.toml")):
        clean_subproject(toml_path)


if __name__ == "__main__":
    main()
