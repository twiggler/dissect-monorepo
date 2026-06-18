"""Shared helper functions for integration tests."""

import subprocess
import tomllib
from pathlib import Path


def version(monorepo: Path, name: str) -> str:
    path = monorepo / "projects" / name / "pyproject.toml"
    return tomllib.loads(path.read_text())["project"]["version"]


def add_tag(monorepo: Path, name: str, ver: str) -> None:
    subprocess.run(["git", "tag", f"{name}/{ver}"], cwd=monorepo, check=True, capture_output=True)


def add_commit(monorepo: Path, project_name: str, message: str = "ci: test commit") -> None:
    """Touch a file inside the project directory and commit it."""
    marker = monorepo / "projects" / project_name / ".bump-test"
    marker.touch()
    subprocess.run(["git", "add", str(marker)], cwd=monorepo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", message],
        cwd=monorepo,
        check=True,
        capture_output=True,
    )
