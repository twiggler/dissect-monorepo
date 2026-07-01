"""Shared fixtures for monorepo-scripts integration tests."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def bump_version_script(request):
    """Path to bump_version.py — lives at the pytest rootdir (.monorepo/)."""
    return Path(request.config.rootdir) / "bump_version.py"


@pytest.fixture(scope="session")
def monorepo_source(tmp_path_factory, request):
    """Session-scoped fixture providing a built monorepo directory.

    Reuses the directory pointed to by MONOREPO_FIXTURE for fast local
    iteration; builds a fresh one via migrate/run_pipeline.sh on CI.
    Read-only tests may use this fixture directly. Mutating tests must
    use the function-scoped ``monorepo`` fixture instead.
    """
    src = os.environ.get("MONOREPO_FIXTURE")
    if src:
        return Path(src)

    # migrate/run_pipeline.sh refuses if the target already exists, so pass a path
    # inside the base temp dir that has not been created yet.
    scripts_dir = Path(request.config.rootdir).parent.parent
    target = tmp_path_factory.getbasetemp() / "monorepo-source"
    # gc.autoDetach=false makes every auto-triggered gc run synchronously so no
    # background gc process outlives run_pipeline.sh.
    no_bg_gc_env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "gc.autoDetach",
        "GIT_CONFIG_VALUE_0": "false",
    }
    subprocess.run(
        ["bash", "migrate/run_pipeline.sh", str(target)],
        check=True,
        cwd=scripts_dir,
        env=no_bg_gc_env,
    )
    # Pack any remaining loose objects so shutil.copytree gets a stable snapshot.
    subprocess.run(["git", "gc"], check=True, cwd=target)
    return target


@pytest.fixture
def monorepo(monorepo_source, tmp_path):
    """Function-scoped fixture providing a writable copy of the monorepo."""

    dest = tmp_path / "monorepo"

    # 1. Copy the repository state exactly as it exists
    shutil.copytree(monorepo_source, dest)

    # 2. Remove historical release tags so tests can create them without conflicts.
    # Migration tags (migration/start/*, migration/end) are preserved because
    # several tests rely on them for bump-auto logic.
    all_tags = subprocess.run(
        ["git", "tag", "-l"], cwd=dest, check=True, capture_output=True, text=True
    ).stdout.splitlines()

    release_tags = [t for t in all_tags if not t.startswith("migration/")]

    if release_tags:
        subprocess.run(
            ["git", "tag", "-d", *release_tags],
            cwd=dest,
            check=True,
            capture_output=True,
        )

    yield dest

    # 3. Cleanup
    shutil.rmtree(dest, ignore_errors=True)
