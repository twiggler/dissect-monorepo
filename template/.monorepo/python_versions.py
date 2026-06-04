#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "packaging",
# ]
# ///
"""
Exposes the configured Python version list from [tool.monorepo.test] in the root
pyproject.toml.  The same list drives both the CI test matrix and the native wheel
build targets (wheels are built for exactly the versions we test against).

Usage:
    # For the CI generate-matrix job (outputs "matrix=<json>" for GITHUB_OUTPUT):
    python3 .monorepo/python_versions.py --format json >> $GITHUB_OUTPUT

    # For local just recipes (one Python version per line):
    uv run --group dev python .monorepo/python_versions.py --format versions

    # For cibuildwheel CIBW_BUILD (space-separated identifiers on one line):
    uv run --group dev python .monorepo/python_versions.py --format cibw-build

    # For the --py-limited-api flag (e.g. "cp310" — minimum CPython version):
    uv run --group dev python .monorepo/python_versions.py --format min-cpython-abi
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(newline="\n")

WORKSPACE_ROOT = Path(__file__).parent.parent


def load_config() -> dict:
    pyproject = WORKSPACE_ROOT / "pyproject.toml"
    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["monorepo"]["test"]


def version_to_cibw_id(version: str) -> str:
    """Convert a Python version string to a cibuildwheel build identifier prefix.

    Examples:
        "3.11"      -> "cp311-*"
        "3.12"      -> "cp312-*"
        "pypy3.11"  -> "pp311-*"
    """
    if version.startswith("pypy"):
        numeric = version[len("pypy"):].replace(".", "")
        return f"pp{numeric}-*"
    return f"cp{version.replace('.', '')}-*"


def min_cpython_abi(versions: list[str]) -> str:
    """Return the abi3 tag for the minimum CPython version in *versions*.

    Ignores PyPy entries. Raises ValueError if no CPython version is present.

    Examples:
        ["3.10", "3.11", "pypy3.11"] -> "cp310"
        ["3.12"]                       -> "cp312"
    """
    cpython = [v for v in versions if not v.startswith("pypy")]
    if not cpython:
        raise ValueError("No CPython version found in python-versions")
    minimum = min(cpython, key=lambda v: tuple(int(x) for x in v.split(".")))
    return "cp" + minimum.replace(".", "")


def cibw_build_string(versions: list[str]) -> str:
    """Return the full CIBW_BUILD value for the given version list."""
    ids = [version_to_cibw_id(v) for v in versions]
    return " ".join(ids)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--format",
        choices=["json", "versions", "cibw-build", "min-cpython-abi"],
        required=True,
        help=(
            "'json' for CI GITHUB_OUTPUT, "
            "'versions' for local iteration, "
            "'cibw-build' for CIBW_BUILD env var, "
            "'min-cpython-abi' for --py-limited-api (e.g. cp310)"
        ),
    )
    args = parser.parse_args()

    config = load_config()
    versions = config["python-versions"]

    if args.format == "json":
        payload = {
            "python-version": versions,
            "os": config["os"],
            "variant": ["source", "native"],
        }
        print(f"matrix={json.dumps(payload)}")
    elif args.format == "versions":
        for version in versions:
            print(version)
    elif args.format == "cibw-build":
        print(cibw_build_string(versions))
    else:
        print(min_cpython_abi(versions))


if __name__ == "__main__":
    main()
