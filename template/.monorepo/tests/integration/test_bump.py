"""Integration tests for the 'just bump' recipe.

Verifies that just bump:
- Increments the minor version of a tagged project with new commits
- Refuses to bump a project whose current version has no release tag (double-bump guard)
- Refuses to bump a project that has a tag only for an older version (stale tag)
- Rejects a batch bump when any target is untagged
- Refuses to bump a project with no new commits since its last release tag
- Refuses a batch bump when any target has no new commits
"""

import subprocess

import helpers

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


_version = helpers.version
_add_tag = helpers.add_tag
_add_commit = helpers.add_commit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bump_increments_minor_version(monorepo):
    """bump increments the minor component and resets the patch to 0."""
    name = "dissect.util"
    original = _version(monorepo, name)
    _add_tag(monorepo, name, original)
    _add_commit(monorepo, name)

    result = _run_bump(monorepo, name)
    assert result.returncode == 0, result.stderr

    new = _version(monorepo, name)
    orig_minor = int(original.split(".")[1])
    new_parts = new.split(".")
    assert int(new_parts[1]) == orig_minor + 1
    assert len(new_parts) == 2


def test_double_bump_guard_rejects_untagged(monorepo):
    """bump refuses to bump a project whose current version has no release tag."""
    result = _run_bump(monorepo, "dissect.util")
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_double_bump_guard_rejects_stale_tag(monorepo):
    """bump refuses to bump a project that has a tag for an older version but not the current one."""
    name = "dissect.util"
    _add_tag(monorepo, name, "0.0.0")

    result = _run_bump(monorepo, name)
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_batch_bump_rejects_if_any_target_untagged(monorepo):
    """In a batch bump, a single untagged project causes the whole operation to fail."""
    # Tag dissect.util but leave dissect.cstruct untagged.
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))

    result = _run_bump(monorepo, "dissect.util", "dissect.cstruct")
    assert result.returncode != 0
    assert "dissect.cstruct" in result.stderr


def test_bump_does_not_modify_file_on_guard_failure(monorepo):
    """When the double-bump guard fires, pyproject.toml is left untouched."""
    original = _version(monorepo, "dissect.util")

    _run_bump(monorepo, "dissect.util")

    assert _version(monorepo, "dissect.util") == original


def test_bump_errors_if_named_package_has_no_new_commits(monorepo):
    """bump refuses to bump a tagged project that has no new commits since the tag."""
    name = "dissect.util"
    _add_tag(monorepo, name, _version(monorepo, name))
    # No commit added — nothing to release.
    result = _run_bump(monorepo, name)
    assert result.returncode != 0
    assert "no new commits" in result.stderr
    assert name in result.stderr


def test_bump_errors_if_any_in_batch_has_no_new_commits(monorepo):
    """In a batch bump, a single project with no new commits causes the whole operation to fail."""
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))
    _add_commit(monorepo, "dissect.util")
    _add_tag(monorepo, "dissect.cstruct", _version(monorepo, "dissect.cstruct"))
    # dissect.cstruct has no new commits.
    result = _run_bump(monorepo, "dissect.util", "dissect.cstruct")
    assert result.returncode != 0
    assert "no new commits" in result.stderr
    assert "dissect.cstruct" in result.stderr
