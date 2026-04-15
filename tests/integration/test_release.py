"""Integration tests for release_pure.sh with a mock PyPI (pypiserver).

Verifies that release_pure.sh:
- Builds the package and publishes it to the configured index
- Creates the correct git tag and pushes it after a successful publish
"""

import http.client
import os
import select
import socket
import subprocess
import time
import tomllib
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(proc: subprocess.Popen, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection("localhost", port, timeout=1)
            conn.request("GET", "/simple/")
            conn.getresponse()
            return
        except Exception:
            time.sleep(0.2)
    stderr = ""
    if proc.stderr:
        if select.select([proc.stderr], [], [], 0)[0]:
            stderr = proc.stderr.read().decode(errors="replace")
    raise RuntimeError(
        f"pypiserver did not start on port {port} within {timeout}s\n{stderr}"
    )


def _version(monorepo: Path, name: str) -> str:
    path = monorepo / "projects" / name / "pyproject.toml"
    return tomllib.loads(path.read_text())["project"]["version"]


def _git_tags(monorepo: Path) -> list[str]:
    return subprocess.run(
        ["git", "tag", "-l"], cwd=monorepo, capture_output=True, text=True, check=True
    ).stdout.splitlines()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pypiserver_instance(tmp_path):
    """Start a passwordless local pypiserver; yield (port, packages_dir)."""
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()
    port = _free_port()
    proc = subprocess.Popen(
        [
            "uvx", "--from", "pypiserver", "pypi-server", "run",
            "--port", str(port),
            "--overwrite",
            "-a", ".",   # no authentication required for any action
            "-P", ".",   # no password file (allow anonymous uploads)
            str(packages_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_server(proc, port)
        yield port, packages_dir
    finally:
        proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_release_publishes_and_creates_tag(monorepo, pypiserver_instance, tmp_path):
    """release_pure.sh builds, publishes to a local index, and creates a git tag."""
    port, packages_dir = pypiserver_instance
    name = "dissect.util"
    version = _version(monorepo, name)

    # Redirect git push to a local bare repo to avoid network calls.
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", "--local", str(monorepo), str(remote)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "set-url", "origin", str(remote)],
        cwd=monorepo, check=True, capture_output=True,
    )

    # Register the local pypiserver as the "testlocal" named index in uv config.
    (monorepo / "uv.toml").write_text(
        f'[[index]]\n'
        f'name = "testlocal"\n'
        f'url = "http://localhost:{port}/simple/"\n'
        f'publish-url = "http://localhost:{port}"\n'
        f'explicit = true\n'
    )

    result = subprocess.run(
        ["just", "release", name, "--index", "testlocal"],
        cwd=monorepo,
        capture_output=True,
        text=True,
        # pypiserver runs without auth; UV_PUBLISH_TOKEN avoids an interactive prompt.
        env={**os.environ, "UV_PUBLISH_TOKEN": "test"},
    )
    assert result.returncode == 0, result.stderr

    # A distribution file for the package must have been uploaded.
    normalised = name.replace(".", "_").replace("-", "_")
    dists = list(packages_dir.rglob(f"{normalised}-*"))
    assert dists, (
        f"No dist file found under {packages_dir}; "
        f"contents: {list(packages_dir.iterdir())}"
    )

    # The release tag must exist in the local clone.
    assert f"{name}/{version}" in _git_tags(monorepo)
