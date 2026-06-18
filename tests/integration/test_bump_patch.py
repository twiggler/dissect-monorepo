"""Integration tests for the 'just bump-patch' recipe.

Verifies that just bump-patch:
- Increments only the patch component, preserving major.minor
- Refuses to bump a package whose current version has no release tag (double-bump guard)
- Refuses to bump a package with no new commits since its last release tag
- Rejects a batch bump when any target is untagged
- Rejects a batch bump when any target has no new commits
- Rejects 'auto' as the package argument
"""

import subprocess

import helpers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_bump_patch(monorepo, *packages):
    return subprocess.run(
        ["just", "bump-patch", *packages],
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


def test_bump_patch_increments_patch_component(monorepo):
    """bump-patch increments only the patch component; major.minor are unchanged."""
    name = "dissect.util"
    original = _version(monorepo, name)
    _add_tag(monorepo, name, original)
    _add_commit(monorepo, name)

    result = _run_bump_patch(monorepo, name)
    assert result.returncode == 0, result.stderr

    new = _version(monorepo, name)
    orig_parts = original.split(".")
    new_parts = new.split(".")

    # Always 3-part result
    assert len(new_parts) == 3
    # major.minor preserved
    assert new_parts[0] == orig_parts[0]
    assert new_parts[1] == orig_parts[1]
    # patch incremented by 1 (original patch is 0 when stored as M.m)
    orig_patch = int(orig_parts[2]) if len(orig_parts) == 3 else 0
    assert int(new_parts[2]) == orig_patch + 1


def test_bump_patch_double_bump_guard_rejects_untagged(monorepo):
    """bump-patch refuses to bump a package whose current version has no release tag."""
    result = _run_bump_patch(monorepo, "dissect.util")
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_bump_patch_double_bump_guard_rejects_stale_tag(monorepo):
    """bump-patch refuses to bump a package that has a tag for an older version but not the current one."""
    name = "dissect.util"
    _add_tag(monorepo, name, "0.0.0")

    result = _run_bump_patch(monorepo, name)
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_bump_patch_errors_if_no_new_commits(monorepo):
    """bump-patch refuses to bump a tagged package with no new commits since the tag."""
    name = "dissect.util"
    _add_tag(monorepo, name, _version(monorepo, name))

    result = _run_bump_patch(monorepo, name)
    assert result.returncode != 0
    assert "no new commits" in result.stderr
    assert name in result.stderr


def test_bump_patch_batch_rejects_if_any_target_untagged(monorepo):
    """In a batch patch-bump, a single untagged package causes the whole operation to fail."""
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))

    result = _run_bump_patch(monorepo, "dissect.util", "dissect.cstruct")
    assert result.returncode != 0
    assert "dissect.cstruct" in result.stderr


def test_bump_patch_batch_rejects_if_any_target_has_no_new_commits(monorepo):
    """In a batch patch-bump, a single package with no new commits causes the whole operation to fail."""
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))
    _add_commit(monorepo, "dissect.util")
    _add_tag(monorepo, "dissect.cstruct", _version(monorepo, "dissect.cstruct"))
    # dissect.cstruct has no new commits
    result = _run_bump_patch(monorepo, "dissect.util", "dissect.cstruct")
    assert result.returncode != 0
    assert "no new commits" in result.stderr
    assert "dissect.cstruct" in result.stderr


def test_bump_patch_does_not_modify_file_on_guard_failure(monorepo):
    """When a guard fires, pyproject.toml is left untouched."""
    original = _version(monorepo, "dissect.util")

    _run_bump_patch(monorepo, "dissect.util")

    assert _version(monorepo, "dissect.util") == original


def test_bump_patch_auto_is_rejected(monorepo):
    """'auto' is not a valid argument for bump-patch."""
    result = subprocess.run(
        ["just", "bump-patch", "auto"],
        cwd=monorepo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "auto" in result.stderr
