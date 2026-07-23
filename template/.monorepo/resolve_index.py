#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Resolve a release role (production/test) to its configured package index name.

Reads [tool.monorepo.release] from the root pyproject.toml:
    production-index  (default "pypi")
    test-index        (default "testpypi")

The resolved name is used as `uv publish --index <name>`; it must match an index uv knows
about (defined in [[tool.uv.index]] in pyproject.toml or [[index]] in uv.toml). Usage:

    resolve_index.py <production|test>

Prints the resolved index name to stdout.
"""

import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(newline="\n")

DEFAULTS = {"production": "pypi", "test": "testpypi"}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in DEFAULTS:
        print("usage: resolve_index.py <production|test>", file=sys.stderr)
        return 2

    role = sys.argv[1]
    data = tomllib.loads(Path("pyproject.toml").read_text())
    release = data.get("tool", {}).get("monorepo", {}).get("release", {})
    print(release.get(f"{role}-index", DEFAULTS[role]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
