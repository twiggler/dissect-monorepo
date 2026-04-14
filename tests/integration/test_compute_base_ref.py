"""Integration tests for compute-base-ref.sh.

Verifies that the script writes the correct ``ref=`` value to GITHUB_OUTPUT
for the two event types it handles, and that the force-push fallback fires
when the supplied SHA is missing from local history."""

import os
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _head_sha(cwd):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _run_script(cwd, output_file, **env_vars):
    env = {**os.environ, "GITHUB_OUTPUT": str(output_file), **env_vars}
    return subprocess.run(
        ["bash", ".monorepo/compute-base-ref.sh"],
        cwd=cwd, capture_output=True, text=True, env=env,
    )


def _parse_output(output_file):
    """Return a dict of key=value pairs written to GITHUB_OUTPUT."""
    pairs = {}
    for line in Path(output_file).read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            pairs[k] = v
    return pairs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pull_request_uses_pr_base_sha(monorepo_source, tmp_path):
    """pull_request event: ref must equal PR_BASE_SHA."""
    sha = _head_sha(monorepo_source)
    out = tmp_path / "github_output"
    out.touch()

    result = _run_script(
        monorepo_source, out,
        EVENT_NAME="pull_request",
        PR_BASE_SHA=sha,
        BEFORE_SHA="",
    )
    assert result.returncode == 0
    assert _parse_output(out)["ref"] == sha


def test_regular_push_uses_before_sha(monorepo_source, tmp_path):
    """Regular push: ref must equal BEFORE_SHA."""
    sha = _head_sha(monorepo_source)
    out = tmp_path / "github_output"
    out.touch()

    result = _run_script(
        monorepo_source, out,
        EVENT_NAME="push",
        PR_BASE_SHA="",
        BEFORE_SHA=sha,
    )
    assert result.returncode == 0
    assert _parse_output(out)["ref"] == sha


def test_missing_before_sha_falls_back_to_head_caret(monorepo_source, tmp_path):
    """A BEFORE_SHA absent from local history triggers the HEAD^ fallback with a warning."""
    out = tmp_path / "github_output"
    out.touch()

    result = _run_script(
        monorepo_source, out,
        EVENT_NAME="push",
        PR_BASE_SHA="",
        BEFORE_SHA="a" * 40,   # valid-length hex but not present in the repo
    )
    assert result.returncode == 0
    assert _parse_output(out)["ref"] == "HEAD^"
    assert "::warning::" in result.stdout
