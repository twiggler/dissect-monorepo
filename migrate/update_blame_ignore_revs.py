#!/usr/bin/env python3
"""Translate and aggregate .git-blame-ignore-revs into the monorepo root.

Usage: update_blame_ignore_revs.py <repo_path> <commit_map_file>

For each project migrated into the monorepo, git filter-repo rewrites all
commit SHAs. This script:
  1. Loads the commit-map produced by filter-repo (old-sha → new-sha).
  2. Reads projects/<repo_path>/.git-blame-ignore-revs (no-op if absent).
  3. Translates every SHA line to its new value; preserves comments/blanks.
  4. Appends a labelled section to the root-level .git-blame-ignore-revs.
  5. Deletes the per-project file (non-functional in a monorepo anyway, since
     git config blame.ignoreRevsFile only supports one file at the repo root).
"""

import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load_commit_map(commit_map_path: Path) -> dict[str, str]:
    mapping = {}
    for line in commit_map_path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            old, new = parts
            mapping[old] = new
    return mapping


def translate(
    lines: list[str], commit_map: dict[str, str], repo_path: str
) -> list[str]:
    result = []
    for line in lines:
        stripped = line.rstrip("\n")
        if SHA_RE.match(stripped):
            new_sha = commit_map.get(stripped)
            if new_sha is None:
                print(
                    f"  [warn] {repo_path}: SHA {stripped} not found in commit map, skipping",
                    file=sys.stderr,
                )
                continue
            result.append(new_sha)
        else:
            result.append(stripped)
    return result


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <repo_path> <commit_map_file>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    commit_map_path = Path(sys.argv[2])
    per_project_file = Path(f"projects/{repo_path}/.git-blame-ignore-revs")
    root_file = Path(".git-blame-ignore-revs")

    if not per_project_file.exists():
        return

    commit_map = load_commit_map(commit_map_path)
    lines = per_project_file.read_text().splitlines()
    translated = translate(lines, commit_map, repo_path)

    # Only append if there are any non-comment, non-blank lines after translation
    has_shas = any(SHA_RE.match(line) for line in translated)
    if has_shas:
        with root_file.open("a") as f:
            f.write(f"\n# {repo_path}\n")
            f.write("\n".join(translated))
            f.write("\n")

    per_project_file.unlink()
    print(f"  [✓] {repo_path}: translated .git-blame-ignore-revs")


if __name__ == "__main__":
    main()
