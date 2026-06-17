"""Integration tests for the 'just pending-releases' recipe.

Verifies that just pending-releases correctly identifies packages
whose current version has no matching git tag (``<name>/<version>``).
"""

import subprocess
import tomllib

import tomlkit

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
    subprocess.run(["git", "tag", f"{name}/{version}"], cwd=monorepo, check=True, capture_output=True)


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


def test_tagged_with_alternate_patch_form(monorepo):
    """A package tagged as M.m.0 is not pending when pyproject.toml records M.m, and vice versa."""
    _clear_tags(monorepo)
    name = "dissect.util"
    toml_path = monorepo / "projects" / name / "pyproject.toml"
    original_text = toml_path.read_text()
    original_version = _version(monorepo, name)

    # Case 1: store version as M.m, tag as M.m.0
    doc = tomlkit.parse(original_text)
    v = original_version.split(".")
    short_ver = f"{v[0]}.{v[1]}"
    long_ver = f"{v[0]}.{v[1]}.0"
    doc["project"]["version"] = short_ver
    toml_path.write_text(tomlkit.dumps(doc))
    _add_tag(monorepo, name, long_ver)

    result = _run_pending_releases(monorepo, "--names")
    assert result.returncode == 0, result.stderr
    assert name not in result.stdout.strip().splitlines(), (
        f"Expected {name} to be recognised via alternate tag {name}/{long_ver}"
    )

    # Case 2: store version as M.m.0, tag as M.m
    subprocess.run(["git", "tag", "-d", f"{name}/{long_ver}"], cwd=monorepo, check=True, capture_output=True)
    doc["project"]["version"] = long_ver
    toml_path.write_text(tomlkit.dumps(doc))
    _add_tag(monorepo, name, short_ver)

    result = _run_pending_releases(monorepo, "--names")
    assert result.returncode == 0, result.stderr
    assert name not in result.stdout.strip().splitlines(), (
        f"Expected {name} to be recognised via alternate tag {name}/{short_ver}"
    )

    # Restore
    toml_path.write_text(original_text)
