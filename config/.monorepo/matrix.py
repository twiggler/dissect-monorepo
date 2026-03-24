#!/usr/bin/env python3
"""
Print the test matrix defined in [tool.monorepo.test] of the root pyproject.toml.

Usage:
    # For the CI generate-matrix job (outputs "matrix=<json>" for GITHUB_OUTPUT):
    python3 .monorepo/matrix.py --format json >> $GITHUB_OUTPUT

    # For local just recipes (one Python version per line):
    uv run --group dev python .monorepo/matrix.py --format versions
"""

import argparse
import json
import tomllib
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).parent.parent


def load_matrix() -> dict:
    pyproject = WORKSPACE_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["monorepo"]["test"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--format",
        choices=["json", "versions"],
        required=True,
        help="Output format: 'json' for CI GITHUB_OUTPUT, 'versions' for local iteration",
    )
    args = parser.parse_args()

    matrix = load_matrix()

    if args.format == "json":
        payload = {
            "python-version": matrix["python-versions"],
            "os": matrix["os"],
        }
        print(f"matrix={json.dumps(payload)}")
    else:
        for version in matrix["python-versions"]:
            print(version)


if __name__ == "__main__":
    main()
