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


def _add_tag(monorepo, name, version):
    subprocess.run(["git", "tag", f"{name}/{version}"], cwd=monorepo, check=True, capture_output=True)


def _add_commit(monorepo, project_name, message="ci: test commit"):
    """Touch a file inside the project directory and commit it."""
    marker = monorepo / "projects" / project_name / ".auto-bump-test"
    marker.touch()
    subprocess.run(
        ["git", "add", str(marker)],
        cwd=monorepo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", message],
        cwd=monorepo,
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_auto_bumps_package_with_new_commits(monorepo):
    """A package with a release tag and new commits gets bumped."""
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
    name = "dissect.util"
    original = _version(monorepo, name)
    _add_tag(monorepo, name, original)

    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr
    assert _version(monorepo, name) == original


def test_auto_silently_skips_pending_packages(monorepo):
    """Packages with no release tag are skipped without error."""
    # No tags at all — every package is pending.
    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr
    assert "Nothing to auto-bump." in result.stdout


def test_auto_mixed_scenario(monorepo):
    """Only tagged packages with new commits are bumped; others are skipped."""
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


def test_auto_migration_commits_do_not_trigger_bump(monorepo):
    """Migration commits must not cause packages to be auto-bumped.

    The monorepo fixture is built by the migration pipeline, which already
    places migration/start/<name> and migration/end.  Only the release tags need
    to be added to simulate a freshly migrated state.

    Expected: bump auto reports "Nothing to auto-bump."
    """
    # Tag every package at its current version (simulating post-migration releases).
    for toml_path in sorted((monorepo / "projects").glob("*/pyproject.toml")):
        import tomllib

        data = tomllib.loads(toml_path.read_text())
        name = data["project"]["name"]
        version = data["project"]["version"]
        _add_tag(monorepo, name, version)

    result = _run_bump_auto(monorepo)
    assert result.returncode == 0, result.stderr
    assert "Nothing to auto-bump." in result.stdout


def test_pre_migration_commits_trigger_bump(tmp_path, bump_version_script):
    """A commit made before the migration must still trigger a bump.

    This test builds a minimal scratch repo to control the exact git history
    without disturbing the structural tags in the real monorepo fixture:

      A  (release tag dissect.util/1.0.0)
      B  (unreleased work in projects/dissect.util)  ← must be detected
      M  (merge commit — tagged migration/start/dissect.util)
      M2 (tagged migration/end)
    """
    repo = tmp_path / "repo"
    pkg_dir = repo / "projects" / "dissect.util"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "pyproject.toml").write_text('[project]\nname = "dissect.util"\nversion = "1.0.0"\n')

    def git(*args):
        subprocess.run(
            ["git", "-c", "user.email=t@t.com", "-c", "user.name=T", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    git("init")
    git("add", "-A")
    git("commit", "-m", "initial")  # A
    git("tag", "dissect.util/1.0.0")  # release tag

    (pkg_dir / ".work").touch()
    git("add", "-A")
    git("commit", "-m", "feat: pre-migration work")  # B

    git("commit", "--allow-empty", "-m", "Merge dissect.util into monorepo")  # M
    git("tag", "migration/start/dissect.util")

    git("commit", "--allow-empty", "-m", "chore: finalize migration")  # M2
    git("tag", "migration/end")

    result = subprocess.run(
        ["uv", "run", str(bump_version_script), "bump", "auto"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "dissect.util" in result.stdout

    version = tomllib.loads((pkg_dir / "pyproject.toml").read_text())["project"]["version"]
    assert version == "1.1.0", f"Expected 1.1.0, got {version}"
