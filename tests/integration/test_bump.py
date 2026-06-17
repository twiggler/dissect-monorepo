"""Integration tests for the 'just bump' recipe.

Verifies that just bump:
- Increments the minor version of a tagged package with new commits
- Refuses to bump a package whose current version has no release tag (double-bump guard)
- Refuses to bump a package that has a tag only for an older version (stale tag)
- Rejects a batch bump when any target is untagged
- Refuses to bump a package with no new commits since its last release tag
- Refuses a batch bump when any target has no new commits
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


def _add_tag(monorepo, name, version):
    subprocess.run(["git", "tag", f"{name}/{version}"], cwd=monorepo, check=True, capture_output=True)


def _add_commit(monorepo, project_name, message="ci: test commit"):
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
    """bump refuses to bump a package whose current version has no release tag."""
    result = _run_bump(monorepo, "dissect.util")
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_double_bump_guard_rejects_stale_tag(monorepo):
    """bump refuses to bump a package that has a tag for an older version but not the current one."""
    name = "dissect.util"
    _add_tag(monorepo, name, "0.0.0")

    result = _run_bump(monorepo, name)
    assert result.returncode != 0
    assert "no release tag" in result.stderr


def test_batch_bump_rejects_if_any_target_untagged(monorepo):
    """In a batch bump, a single untagged package causes the whole operation to fail."""
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
    """bump refuses to bump a tagged package that has no new commits since the tag."""
    name = "dissect.util"
    _add_tag(monorepo, name, _version(monorepo, name))
    # No commit added — nothing to release.
    result = _run_bump(monorepo, name)
    assert result.returncode != 0
    assert "no new commits" in result.stderr
    assert name in result.stderr


def test_bump_errors_if_any_in_batch_has_no_new_commits(monorepo):
    """In a batch bump, a single package with no new commits causes the whole operation to fail."""
    _add_tag(monorepo, "dissect.util", _version(monorepo, "dissect.util"))
    _add_commit(monorepo, "dissect.util")
    _add_tag(monorepo, "dissect.cstruct", _version(monorepo, "dissect.cstruct"))
    # dissect.cstruct has no new commits.
    result = _run_bump(monorepo, "dissect.util", "dissect.cstruct")
    assert result.returncode != 0
    assert "no new commits" in result.stderr
    assert "dissect.cstruct" in result.stderr
