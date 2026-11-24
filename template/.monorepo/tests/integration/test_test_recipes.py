"""Integration tests for the Justfile recipes that test several projects.

Runs the test recipes from the real Justfile against a tiny synthetic workspace instead
of the monorepo fixture, so each test takes seconds. Verifies that:
- a failing project does not stop the run, and the failed projects are listed at the end
- a project without tests does not count as a failure
- Ctrl-C stops the whole run instead of only the current project
- test-affected fails on an unknown ref instead of reporting "nothing affected"
- test-affected sees new files that are not yet git-added
- extra pytest arguments reach pytest intact
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

# tests/integration/ -> .monorepo/ -> the monorepo root, which holds the Justfile.
MONOREPO_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = MONOREPO_DIR.parent
# The scripts the tested recipes call.
TOOLING_FILES = ["tooling-python", "affected_tests.py", "python_versions.py"]

# The interpreter running this test is certainly available to uv.
PY = f"{sys.version_info.major}.{sys.version_info.minor}"

PASS = "pass"
FAIL = "assert False, 'deliberate failure'"
HANG = "time.sleep(600)"
NO_TESTS = None

# Every dummy test appends its project name to RECIPE_TEST_LOG before its body runs, so
# the log shows which projects ran and in what order.
TEST_FILE = """\
import os
import time
from pathlib import Path


def test_{name}():
    with Path(os.environ["RECIPE_TEST_LOG"]).open("a") as f:
        f.write("{name}\\n")
    {body}
"""

ROOT_PYPROJECT = """\
[project]
name = "workspace"
version = "0"
requires-python = ">=3.10"

[dependency-groups]
dev = ["pytest", "pytest-xdist"]

[tool.uv.workspace]
members = ["projects/*"]

[tool.monorepo.test]
python-versions = {python_versions}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workspace(root: Path, projects: dict[str, str | None], python_versions: tuple[str, ...] = (PY,)) -> None:
    """Create a uv workspace with the real Justfile and one project per entry.

    ``projects`` maps a project name to the body of its single test, or to NO_TESTS.
    """
    (root / ".monorepo").mkdir(parents=True)
    (root / "Justfile").write_text((ROOT_DIR / "Justfile").read_text())
    for name in TOOLING_FILES:
        (root / ".monorepo" / name).write_text((MONOREPO_DIR / name).read_text())
    versions = "[" + ", ".join(f'"{v}"' for v in python_versions) + "]"
    (root / "pyproject.toml").write_text(ROOT_PYPROJECT.format(python_versions=versions))

    for name, body in projects.items():
        project = root / "projects" / name
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "0"\nrequires-python = ">=3.10"\n'
        )
        if body is not NO_TESTS:
            (project / "tests").mkdir()
            (project / "tests" / f"test_{name}.py").write_text(TEST_FILE.format(name=name, body=body))


def _env(log: Path) -> dict[str, str]:
    # Drop the venv of the pytest run itself; uv would warn that it does not match the
    # workspace's .venv.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["RECIPE_TEST_LOG"] = str(log)
    return env


def _just(root: Path, log: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["just", *args], cwd=root, env=_env(log), capture_output=True, text=True)


def _ran(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _commit_all(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")


def _change(root: Path, *names: str) -> None:
    """Edit the test file of each named project in the working tree."""
    for name in names:
        with (root / "projects" / name / "tests" / f"test_{name}.py").open("a") as f:
            f.write("# changed\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_test_all_continues_after_failure(tmp_path):
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": PASS, "bravo": FAIL, "charlie": PASS})

    result = _just(root, log, "test-all", PY)

    assert result.returncode == 1, result.stderr
    assert _ran(log) == ["alpha", "bravo", "charlie"]
    assert f"Tests FAILED with Python {PY} for: bravo" in result.stderr.splitlines()


def test_test_all_passes_when_no_project_fails(tmp_path):
    """A project without tests (pytest exit code 5) is not a failure."""
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": PASS, "bravo": NO_TESTS, "charlie": PASS})

    result = _just(root, log, "test-all", PY)

    assert result.returncode == 0, result.stderr
    assert _ran(log) == ["alpha", "charlie"]
    assert "FAILED" not in result.stderr


def test_test_affected_continues_after_failure(tmp_path):
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": PASS, "bravo": FAIL, "charlie": PASS})
    _commit_all(root)
    _change(root, "bravo", "charlie")

    result = _just(root, log, "test-affected", "HEAD", PY)

    assert result.returncode == 1, result.stderr
    assert _ran(log) == ["bravo", "charlie"]
    assert f"Tests FAILED with Python {PY} for: bravo" in result.stderr.splitlines()


def test_test_affected_fails_on_unknown_ref(tmp_path):
    """An unknown ref must fail the run, not pass it as "nothing affected"."""
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": PASS})
    _commit_all(root)

    result = _just(root, log, "test-affected", "does-not-exist", PY)

    assert result.returncode != 0
    assert "Nothing to do" not in result.stdout
    assert _ran(log) == []


def test_test_affected_includes_untracked_files(tmp_path):
    """New files count before they are git-added; ignored files do not."""
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": PASS, "bravo": PASS})
    (root / ".gitignore").write_text("*.tmp\n")
    _commit_all(root)
    (root / "projects" / "alpha" / "new_module.py").write_text("x = 1\n")
    (root / "projects" / "bravo" / "scratch.tmp").write_text("ignored\n")

    result = _just(root, log, "test-affected", "HEAD", PY)

    assert result.returncode == 0, result.stderr
    assert _ran(log) == ["alpha"]


def test_test_affected_with_nothing_affected(tmp_path):
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": FAIL})
    (root / "README.md").write_text("docs\n")
    _commit_all(root)
    # A change outside projects/ that is not a global trigger.
    with (root / "README.md").open("a") as f:
        f.write("more docs\n")

    result = _just(root, log, "test-affected", "HEAD", PY)

    assert result.returncode == 0, result.stderr
    assert "No projects affected. Nothing to do." in result.stdout.splitlines()
    assert _ran(log) == []


def test_test_all_envs_continues_after_failure(tmp_path):
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    # Two spellings of the same interpreter give two "versions" without needing a
    # second Python installation.
    versions = (PY, f"cpython{PY}")
    _make_workspace(root, {"alpha": PASS, "bravo": FAIL, "charlie": PASS}, versions)

    result = _just(root, log, "test-all-envs")

    assert result.returncode == 1, result.stderr
    assert _ran(log) == ["alpha", "bravo", "charlie"] * 2
    stderr = result.stderr.splitlines()
    for version in versions:
        assert f"Tests FAILED with Python {version} for: bravo" in stderr
    assert any(line.startswith(f"Tests FAILED with Python {PY} cpython{PY} ") for line in stderr)


def test_extra_pytest_args_are_forwarded_intact(tmp_path):
    """A -k expression with spaces reaches pytest as one argument, via test and test-all.

    The expressions deselect bravo's failing test, which leaves bravo with no tests
    (exit code 5, not a failure). If the arguments were dropped, bravo would fail; if
    the expression were split into words, pytest would reject the arguments.
    """
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": PASS, "bravo": FAIL, "charlie": PASS})

    result = _just(root, log, "test", "bravo", PY, "-k", "not test_bravo")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _ran(log) == []

    result = _just(root, log, "test-all", PY, "-k", "test_alpha or test_charlie")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _ran(log) == ["alpha", "charlie"]


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX process groups")
@pytest.mark.parametrize("recipe", [["test-all", PY], ["test-affected", "HEAD", PY]], ids=lambda r: r[0])
def test_ctrl_c_stops_the_whole_run(tmp_path, recipe):
    root, log = tmp_path / "ws", tmp_path / "ran.log"
    _make_workspace(root, {"alpha": HANG, "bravo": PASS, "charlie": PASS})
    # Affects all three projects, for test-affected.
    _commit_all(root)
    _change(root, "alpha", "bravo", "charlie")

    # A new session gives just and everything it starts their own process group, so
    # the SIGINT below reaches only them and not this pytest run.
    with (tmp_path / "just.out").open("w") as out:
        proc = subprocess.Popen(
            ["just", *recipe],
            cwd=root,
            env=_env(log),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        # Wait until alpha's test has started (and is sleeping).
        deadline = time.monotonic() + 120
        while "alpha" not in _ran(log):
            assert proc.poll() is None, (tmp_path / "just.out").read_text()
            assert time.monotonic() < deadline, "alpha's test did not start"
            time.sleep(0.1)

        # A terminal sends Ctrl-C to the whole foreground process group. Signalling
        # only the top-level just would not reach the loop or pytest: just waits for
        # its recipe to finish on its own.
        os.killpg(proc.pid, signal.SIGINT)
        returncode = proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

    assert returncode == 130, (tmp_path / "just.out").read_text()
    assert _ran(log) == ["alpha"]
