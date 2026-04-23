"""Integration tests for the 'just bump-auto' recipe.

Verifies that just bump-auto:
- Bumps packages that have a release tag AND new commits since that tag
- Skips packages with a release tag but no new commits since it
- Silently skips (no error) packages that are pending release (no tag)
- Handles a mix of all three cases correctly
"""

import subprocess
import tomllib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_bump_auto(monorepo):
    return subprocess.run(
        ["just", "bump", "auto"],
        cwd=monorepo,
        capture_output=True,
        text=True,
    )


def _version(monorepo, name):
    path = monorepo / "projects" / name / "pyproject.toml"
    return tomllib.loads(path.read_text())["project"]["version"]


def _minor(version: str) -> int:
    return int(version.split(".")[1])


def _clear_tags(monorepo):
    tags = subprocess.run(
        ["git", "tag", "-l"], cwd=monorepo, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for tag in tags:
        subprocess.run(["git", "tag", "-d", tag], cwd=monorepo, check=True, capture_output=True)


def _add_tag(monorepo, name, version):
    subprocess.run(
        ["git", "tag", f"{name}/{version}"], cwd=monorepo, check=True, capture_output=True
    )


def _add_commit(monorepo, project_name, message="ci: test commit"):
    """Touch a file inside the project directory and commit it."""
    marker = monorepo / "projects" / project_name / ".auto-bump-test"
    marker.touch()
    subprocess.run(
        ["git", "add", str(marker)],
        cwd=monorepo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
         "commit", "-m", message],
        cwd=monorepo, check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_auto_bumps_package_with_new_commits(monorepo):
    """A package with a release tag and new commits gets bumped."""
    _clear_tags(monorepo)
    name = "dissect.util"
    original = _version(monorepo, name)
    _add_tag(monorepo, name, original)
    _add_commit(monorepo, name)

    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr

    new = _version(monorepo, name)
    assert _minor(new) == _minor(original) + 1
    assert new.split(".")[2] == "0"


def test_auto_skips_package_without_new_commits(monorepo):
    """A package with a release tag but no new commits is not bumped."""
    _clear_tags(monorepo)
    name = "dissect.util"
    original = _version(monorepo, name)
    _add_tag(monorepo, name, original)

    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr
    assert _version(monorepo, name) == original


def test_auto_silently_skips_pending_packages(monorepo):
    """Packages with no release tag are skipped without error."""
    _clear_tags(monorepo)
    # No tags at all — every package is pending.
    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr
    assert "Nothing to auto-bump." in result.stdout


def test_auto_mixed_scenario(monorepo):
    """Only tagged packages with new commits are bumped; others are skipped."""
    _clear_tags(monorepo)

    util_version = _version(monorepo, "dissect.util")
    cstruct_version = _version(monorepo, "dissect.cstruct")

    # dissect.util: tagged + new commit → should be bumped
    _add_tag(monorepo, "dissect.util", util_version)
    _add_commit(monorepo, "dissect.util")

    # dissect.cstruct: tagged, no new commit → should be skipped
    _add_tag(monorepo, "dissect.cstruct", cstruct_version)

    # all other packages: no tag → silently skipped

    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr

    assert _minor(_version(monorepo, "dissect.util")) == _minor(util_version) + 1
    assert _version(monorepo, "dissect.cstruct") == cstruct_version
