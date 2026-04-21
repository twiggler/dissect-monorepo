#!/usr/bin/env python3
"""Generate the full cibuildwheel build matrix for all platforms.

Reads [tool.monorepo.native] from pyproject.toml and writes a JSON matrix
suitable for `matrix: include: ${{ fromJSON(...) }}` in GitHub Actions.

Each Linux x86 arch gets its own runner entry so that QEMU-emulated builds run
in parallel rather than sequentially on a single runner.

Usage: python .monorepo/resolve_linux_archs.py [--slow]
  --slow   Use linux-x86-archs (full set with QEMU arches) for release builds.
           Without this flag, uses linux-x86-archs-pr (host-only, PR builds).
"""

import argparse
import json
import os
import sys
import tomllib

sys.stdout.reconfigure(newline="\n")

QEMU_MAP = {
    "ppc64le": "linux/ppc64le",
    "s390x": "linux/s390x",
    "armv7l": "linux/arm/v7",
}

# Non-Linux-x86 runners are always included regardless of the --slow flag.
# None of these require QEMU — needs-qemu is derived centrally from qemu-platform presence.
STATIC_ENTRIES = [
    {"runner": "ubuntu-24.04-arm", "platform": "linux-aarch64",  "archs": "aarch64"},
    {"runner": "macos-latest",     "platform": "macos-arm64",    "archs": "arm64"},
    {"runner": "macos-15-intel",   "platform": "macos-x86_64",   "archs": "x86_64"},
    {"runner": "windows-latest",   "platform": "windows-amd64",  "archs": "AMD64"},
    {"runner": "windows-latest",   "platform": "windows-x86",    "archs": "x86"},
    {"runner": "windows-11-arm",   "platform": "windows-arm64",  "archs": "ARM64"},
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slow", action="store_true", help="Use full arch list (with QEMU arches)")
    args = parser.parse_args()

    with open("pyproject.toml", "rb") as f:
        cfg = tomllib.load(f)

    native = cfg["tool"]["monorepo"]["native"]
    key = "linux-x86-archs" if args.slow else "linux-x86-archs-pr"
    archs = native[key]

    # One runner entry per Linux x86 arch so QEMU-emulated builds are parallel.
    linux_entries = []
    linux_entries = [
        {
            "runner": "ubuntu-latest",
            "platform": f"linux-{arch}",
            "archs": arch,
            **({"qemu-platform": qemu_platform} if (qemu_platform := QEMU_MAP.get(arch)) else {}),
        }
        for arch in archs
    ]

    # Derive needs-qemu from the presence of qemu-platform so it never gets out of sync.
    matrix = [
        {**e, "needs-qemu": "true" if "qemu-platform" in e else "false"}
        for e in linux_entries + STATIC_ENTRIES
    ]
    matrix_json = json.dumps(matrix)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as out:
            out.write(f"matrix={matrix_json}\n")
    else:
        # Useful for local debugging.
        print(f"matrix={matrix_json}")


if __name__ == "__main__":
    main()
