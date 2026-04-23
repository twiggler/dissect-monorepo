"""Integration tests for the 'just pending-releases' recipe.

Verifies that just pending-releases correctly identifies packages
whose current version has no matching git tag (``<name>/<version>``).
"""

import subprocess
import tomllib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_pending_releases(monorepo, *args):
    return subprocess.run(
        ["just", "pending-releases", *args],
        cwd=monorepo,
        capture_output=True,
        text=True,
    )


def _version(monorepo, name):
    path = monorepo / "projects" / name / "pyproject.toml"
    return tomllib.loads(path.read_text())["project"]["version"]


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_package_pending_when_untagged(monorepo):
    """All packages appear as pending when no release tags exist."""
    _clear_tags(monorepo)
    result = _run_pending_releases(monorepo, "--names")
    assert result.returncode == 0, result.stderr
    names = result.stdout.strip().splitlines()
    assert "dissect.util" in names
    assert "dissect.cstruct" in names


def test_tagged_package_not_in_pending_list(monorepo):
    """A package with a matching release tag does not appear as pending."""
    _clear_tags(monorepo)
    name = "dissect.util"
    _add_tag(monorepo, name, _version(monorepo, name))

    result = _run_pending_releases(monorepo, "--names")
    assert result.returncode == 0, result.stderr
    names = result.stdout.strip().splitlines()
    assert name not in names


def test_other_packages_still_pending_after_single_tag(monorepo):
    """Tagging one package does not mark others as released."""
    _clear_tags(monorepo)
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))

    result = _run_pending_releases(monorepo, "--names")
    names = result.stdout.strip().splitlines()
    assert "dissect.cstruct" in names


def test_table_output_shows_tagged_and_pending(monorepo):
    """Human-readable table contains both 'tagged' and 'pending' entries."""
    _clear_tags(monorepo)
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))

    result = _run_pending_releases(monorepo)
    assert result.returncode == 0, result.stderr
    assert "tagged" in result.stdout
    assert "pending" in result.stdout
