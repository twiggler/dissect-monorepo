"""Integration tests for the 'just bump' recipe.

Verifies that just bump:
- Increments the minor version of a tagged package
- Refuses to bump a package whose current version has no release tag (double-bump guard)
- Refuses to bump a package that has a tag only for an older version (stale tag)
- Rejects a batch bump when any target is untagged
"""

import subprocess
import tomllib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_bump(monorepo, *packages):
    return subprocess.run(
        ["just", "bump", *packages],
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

def test_bump_increments_minor_version(monorepo):
    """bump increments the minor component and resets the patch to 0."""
    _clear_tags(monorepo)
    name = "dissect.util"
    original = _version(monorepo, name)
    _add_tag(monorepo, name, original)

    result = _run_bump(monorepo, name)
    assert result.returncode == 0, result.stderr

    new = _version(monorepo, name)
    orig_minor = int(original.split(".")[1])
    new_parts = new.split(".")
    assert int(new_parts[1]) == orig_minor + 1
    assert new_parts[2] == "0"


def test_double_bump_guard_rejects_untagged(monorepo):
    """bump refuses to bump a package whose current version has no release tag."""
    _clear_tags(monorepo)
    result = _run_bump(monorepo, "dissect.util")
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_double_bump_guard_rejects_stale_tag(monorepo):
    """bump refuses to bump a package that has a tag for an older version but not the current one."""
    _clear_tags(monorepo)
    name = "dissect.util"
    _add_tag(monorepo, name, "0.0.0")

    result = _run_bump(monorepo, name)
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_batch_bump_rejects_if_any_target_untagged(monorepo):
    """In a batch bump, a single untagged package causes the whole operation to fail."""
    _clear_tags(monorepo)
    # Tag dissect.util but leave dissect.cstruct untagged.
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))

    result = _run_bump(monorepo, "dissect.util", "dissect.cstruct")
    assert result.returncode != 0
    assert "dissect.cstruct" in result.stderr


def test_bump_does_not_modify_file_on_guard_failure(monorepo):
    """When the double-bump guard fires, pyproject.toml is left untouched."""
    _clear_tags(monorepo)
    original = _version(monorepo, "dissect.util")

    _run_bump(monorepo, "dissect.util")

    assert _version(monorepo, "dissect.util") == original
