#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Print the names of workspace projects that have [tool.monorepo] native = true."""

import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(newline="\n")

for p in sorted(Path("projects").glob("*/pyproject.toml")):
    data = tomllib.loads(p.read_text())
    if data.get("tool", {}).get("monorepo", {}).get("native"):
        print(p.parent.name)
