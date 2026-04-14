"""Shared fixtures for monorepo-scripts integration tests."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def monorepo_source(tmp_path_factory):
    """Session-scoped fixture providing a built monorepo directory.

    Reuses the directory pointed to by MONOREPO_FIXTURE for fast local
    iteration; builds a fresh one via run_pipeline.sh on CI.
    Read-only tests may use this fixture directly. Mutating tests must
    use the function-scoped ``monorepo`` fixture instead.
    """
    src = os.environ.get("MONOREPO_FIXTURE")
    if src:
        return Path(src)
    # run_pipeline.sh refuses if the target already exists, so pass a path
    # inside the base temp dir that has not been created yet.
    target = tmp_path_factory.getbasetemp() / "monorepo-source"
    subprocess.run(
        ["bash", "run_pipeline.sh", str(target)],
        check=True,
        cwd=SCRIPTS_DIR,
    )
    return target


@pytest.fixture
def monorepo(monorepo_source, tmp_path):
    """Function-scoped fixture providing a writable copy of the monorepo.

    Uses ``git clone --local`` so that git objects are hardlinked rather than
    copied, keeping per-test disk cost near zero regardless of repository size.
    LFS objects are not cloned — tests don't require binary content.
    """
    dest = tmp_path / "monorepo"
    subprocess.run(
        ["git", "clone", "--local", str(monorepo_source), str(dest)],
        check=True,
        capture_output=True,
    )
    yield dest
    shutil.rmtree(dest, ignore_errors=True)
