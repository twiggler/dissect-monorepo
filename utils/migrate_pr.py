#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Migrate an open PR from a per-package repo to the dissect monorepo.

Usage:
    uv run utils/migrate_pr.py <pr-url> [--monorepo-path PATH] [--dry-run]

Always run with --dry-run first to inspect the rewritten diff and draft PR body
before making any changes.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import httpx

GITHUB_API = "https://api.github.com"
# Files that exist in the old per-package repos but have no place in the monorepo.
# Changes to these files in migrated PRs are dropped and noted in the PR body.
#
# tox.ini        — test runner config, replaced by the Justfile / uv in the monorepo.
# pyproject.toml — was heavily edited during migration (new build backend, dependency
#                  groups, tool config); applying old per-package changes on top of the
#                  migrated version would almost certainly conflict or be incorrect.
DROP_FILES = frozenset({"tox.ini", "pyproject.toml"})


# ── Auth ──────────────────────────────────────────────────────────────────────


def resolve_token() -> str:
    if shutil.which("gh"):
        status = subprocess.run(["gh", "auth", "status"], capture_output=True)
        if status.returncode == 0:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, check=True
            )
            token = result.stdout.strip()
            if token:
                return token

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token

    sys.exit(
        "error: no GitHub token found.\n"
        "  Option 1: run `gh auth login` (gh CLI)\n"
        "  Option 2: set the GITHUB_TOKEN environment variable"
    )


# ── GitHub API ────────────────────────────────────────────────────────────────


def api_get(
    client: httpx.Client,
    path: str,
    *,
    accept: str = "application/vnd.github+json",
) -> httpx.Response:
    resp = client.get(f"{GITHUB_API}{path}", headers={"Accept": accept})
    resp.raise_for_status()
    return resp


def fetch_pr(client: httpx.Client, owner: str, repo: str, pr_number: int) -> dict:
    return api_get(client, f"/repos/{owner}/{repo}/pulls/{pr_number}").json()


def fetch_pr_diff(client: httpx.Client, owner: str, repo: str, pr_number: int) -> str:
    return api_get(
        client,
        f"/repos/{owner}/{repo}/pulls/{pr_number}",
        accept="application/vnd.github.diff",
    ).text


def fetch_pr_commits(
    client: httpx.Client, owner: str, repo: str, pr_number: int
) -> list[dict]:
    return api_get(
        client, f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
    ).json()


def fetch_commit_diff(
    client: httpx.Client, owner: str, repo: str, sha: str
) -> str:
    return api_get(
        client,
        f"/repos/{owner}/{repo}/commits/{sha}",
        accept="application/vnd.github.diff",
    ).text


def fetch_authenticated_user(client: httpx.Client) -> str:
    return api_get(client, "/user").json()["login"]


# ── Path rewriting ────────────────────────────────────────────────────────────


@dataclass
class RewriteResult:
    diff: str
    dropped_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def classify_path(path: str) -> str:
    """Return 'rewrite', 'drop', or 'warn' for a file path from the old repo."""
    if re.match(r"^dissect/", path):
        return "rewrite"
    if re.match(r"^tests/", path):
        return "rewrite"
    if path == "pyproject.toml":
        return "rewrite"
    if path in DROP_FILES:
        return "drop"
    return "warn"


def rewrite_path(path: str, package: str) -> str:
    """Map a 'rewrite'-classified path to its monorepo equivalent."""
    if re.match(r"^dissect/", path):
        return f"projects/{package}/src/{path}"
    if re.match(r"^tests/", path):
        return f"projects/{package}/{path}"
    if path == "pyproject.toml":
        return f"projects/{package}/pyproject.toml"
    return path


def rewrite_diff(raw_diff: str, package: str) -> RewriteResult:
    """Rewrite all file paths in a raw unified diff string for the monorepo layout.

    Returns a RewriteResult with:
      - diff: the rewritten diff text, ready for `git apply`
      - dropped_files: legacy files removed from the diff
      - warnings: unrecognised root-level files kept in the diff
    """
    dropped: list[str] = []
    warnings: list[str] = []

    # Extract source AND destination paths from all `diff --git a/X b/Y` headers.
    # For renames, X != Y and both need to be in the action_map so that
    # `rename from`, `rename to`, `--- a/`, and `+++ b/` lines are all rewritten
    # consistently with the `diff --git` header.
    path_pairs = re.findall(r"^diff --git a/(.+) b/(.+)$", raw_diff, re.MULTILINE)
    source_paths = list(dict.fromkeys(p[0] for p in path_pairs))
    all_paths = list(dict.fromkeys(p for pair in path_pairs for p in pair))

    # Build old_path → new_path mapping ('__drop__' for dropped files).
    action_map: dict[str, str] = {}
    for path in all_paths:
        action = classify_path(path)
        if action == "rewrite":
            action_map[path] = rewrite_path(path, package)
        elif action == "drop":
            action_map[path] = "__drop__"
        else:
            action_map[path] = path  # keep in diff, unmodified

    # Dropped/warnings are reported for source paths only.
    dropped = [p for p in source_paths if action_map[p] == "__drop__"]
    warnings = [p for p in source_paths if action_map[p] == p and classify_path(p) == "warn"]

    diff = raw_diff

    # Remove dropped file blocks entirely (from their `diff --git` line to the
    # start of the next `diff --git` line, or end of string).
    for path in dropped:
        escaped = re.escape(path)
        diff = re.sub(
            rf"^diff --git a/{escaped} b/.*?(?=^diff --git |\Z)",
            "",
            diff,
            flags=re.MULTILINE | re.DOTALL,
        )

    # Rewrite `diff --git a/<old> b/<old>` headers.
    def _replace_git_header(m: re.Match) -> str:
        old_a, old_b = m.group(1), m.group(2)
        new_a = action_map.get(old_a, old_a)
        new_b = action_map.get(old_b, old_b)
        if new_a == "__drop__":
            return m.group(0)
        return f"diff --git a/{new_a} b/{new_b}"

    diff = re.sub(
        r"^diff --git a/(.+) b/(.+)$", _replace_git_header, diff, flags=re.MULTILINE
    )

    # Rewrite `--- a/<old>` lines.
    def _replace_minus(m: re.Match) -> str:
        old = m.group(1)
        new = action_map.get(old, old)
        return m.group(0) if new == "__drop__" else f"--- a/{new}"

    diff = re.sub(r"^--- a/(.+)$", _replace_minus, diff, flags=re.MULTILINE)

    # Rewrite `+++ b/<old>` lines.
    def _replace_plus(m: re.Match) -> str:
        old = m.group(1)
        new = action_map.get(old, old)
        return m.group(0) if new == "__drop__" else f"+++ b/{new}"

    diff = re.sub(r"^\+\+\+ b/(.+)$", _replace_plus, diff, flags=re.MULTILINE)

    # Rewrite `rename from <old>` and `rename to <new>` lines produced for renames.
    # These must match the `diff --git a/` and `b/` paths respectively, otherwise
    # git apply reports "inconsistent old filename".
    def _replace_rename_from(m: re.Match) -> str:
        old = m.group(1)
        new = action_map.get(old, old)
        return m.group(0) if new == "__drop__" else f"rename from {new}"

    diff = re.sub(r"^rename from (.+)$", _replace_rename_from, diff, flags=re.MULTILINE)

    def _replace_rename_to(m: re.Match) -> str:
        old = m.group(1)
        new = action_map.get(old, old)
        return m.group(0) if new == "__drop__" else f"rename to {new}"

    diff = re.sub(r"^rename to (.+)$", _replace_rename_to, diff, flags=re.MULTILINE)

    return RewriteResult(diff=diff, dropped_files=dropped, warnings=warnings)


def diff_is_empty(diff: str) -> bool:
    return not re.search(r"^diff --git ", diff, re.MULTILINE)


# ── Git helpers ───────────────────────────────────────────────────────────────


def git(
    args: list[str],
    *,
    cwd: str,
    env: dict | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=full_env,
        check=check,
        capture_output=True,
        text=True,
    )


def get_remote_url(cwd: str) -> str:
    return git(["remote", "get-url", "origin"], cwd=cwd).stdout.strip()


def parse_remote_url(url: str) -> tuple[str, str]:
    m = re.match(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"https://(?:[^@]+@)?github\.com/([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    sys.exit(f"error: cannot parse GitHub remote URL: {url!r}")


def push_url(remote_url: str, token: str) -> str:
    """Return the URL to use for git push; injects token for HTTPS remotes."""
    if remote_url.startswith("git@"):
        return remote_url
    return re.sub(r"https://", f"https://x-access-token:{token}@", remote_url, count=1)


# ── LFS ───────────────────────────────────────────────────────────────────────


def fetch_lfs_objects(
    source_owner: str,
    source_repo: str,
    head_sha: str,
    token: str,
    cwd: str,
) -> None:
    """Fetch LFS objects at head_sha from the source repo into the local cache.

    Adds a temporary remote, runs `git lfs fetch`, then removes the remote.
    The local cache is then picked up by the git-lfs pre-push hook on `git push`.
    """
    source_url = f"https://x-access-token:{token}@github.com/{source_owner}/{source_repo}.git"
    remote_name = "__lfs_source__"
    git(["remote", "add", remote_name, source_url], cwd=cwd)
    try:
        print("Fetching LFS objects from source ...", file=sys.stderr)
        # First fetch the git objects so the commit SHA exists locally,
        # otherwise `git lfs fetch` fails with "not a tree object" because
        # it calls `git ls-tree` internally to enumerate LFS pointer files.
        git(["fetch", remote_name, head_sha], cwd=cwd, check=False)
        proc = git(["lfs", "fetch", remote_name, "FETCH_HEAD"], cwd=cwd, check=False)
        if proc.returncode != 0:
            print(f"warning: git lfs fetch incomplete:\n{proc.stderr}", file=sys.stderr)
    finally:
        git(["remote", "remove", remote_name], cwd=cwd)


def apply_diff_text(
    diff_text: str, *, cwd: str, check_only: bool = False
) -> subprocess.CompletedProcess:
    args = ["apply"]
    if check_only:
        args.append("--check")
    else:
        args.append("--index")  # stage the changes so `git commit` can pick them up
    # GIT_LFS_SKIP_SMUDGE=1: write LFS pointer files as-is without trying to
    # download objects from the source repo's LFS server, which won't have them.
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
    return subprocess.run(
        ["git", *args],
        input=diff_text,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )


# ── PR body ───────────────────────────────────────────────────────────────────


def build_pr_body(
    *,
    old_pr_url: str,
    maintainer_login: str,
    contributor_login: str,
    original_body: str,
    package_name: str,
    original_base_ref: str,
    dropped_files: list[str],
    warnings: list[str],
) -> str:
    dropped_section = ""
    if dropped_files:
        files = ", ".join(f"`{f}`" for f in dropped_files)
        dropped_section = (
            f"\n- The following files were not migrated (no longer needed after"
            f" `src`-layout migration): {files}"
        )

    warnings_section = ""
    if warnings:
        files = ", ".join(f"`{f}`" for f in warnings)
        warnings_section = (
            f"\n- The following root-level files require maintainer review: {files}"
        )

    body = original_body.strip() or "_No description provided._"

    return (
        f"> [!NOTE]\n"
        f"> Migrated from {old_pr_url} by @{maintainer_login}.\n"
        f"> Original author: @{contributor_login}\n"
        f"\n---\n\n"
        f"{body}\n"
        f"\n---\n\n"
        f"**Migration notes**\n\n"
        f"- Package: `{package_name}`\n"
        f"- Original base branch: `{original_base_ref}`"
        f"{dropped_section}"
        f"{warnings_section}\n"
    )


# ── Input parsing ─────────────────────────────────────────────────────────────


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        sys.exit(f"error: not a valid GitHub PR URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))


def normalize_package_name(repo: str) -> str:
    """dissect-util → dissect.util; dissect.util → dissect.util"""
    return repo.replace("-", ".")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate an open GitHub PR from a per-package repo to the dissect monorepo. "
            "Always run with --dry-run first."
        )
    )
    parser.add_argument("pr_url", metavar="PR_URL", help="Full GitHub URL of the PR to migrate")
    parser.add_argument(
        "--monorepo-path",
        default=".",
        help="Path to the monorepo checkout (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rewritten diff and draft PR body; make no changes",
    )
    args = parser.parse_args()

    monorepo_path = os.path.abspath(args.monorepo_path)

    # Phase 1 — inputs and inference
    owner, repo, pr_number = parse_pr_url(args.pr_url)
    package_name = normalize_package_name(repo)
    remote_url = get_remote_url(monorepo_path)
    monorepo_owner, monorepo_repo = parse_remote_url(remote_url)

    token = resolve_token()
    client_headers = {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    with httpx.Client(headers=client_headers, follow_redirects=True) as client:
        # Phase 2 — fetch PR data
        print(f"Fetching PR data for {args.pr_url} ...", file=sys.stderr)
        pr_data = fetch_pr(client, owner, repo, pr_number)
        title = pr_data["title"]
        original_body = pr_data.get("body") or ""
        contributor_login = pr_data["user"]["login"]
        base_ref = pr_data["base"]["ref"]
        head_sha = pr_data["head"]["sha"]

        print("Fetching PR diff ...", file=sys.stderr)
        raw_diff = fetch_pr_diff(client, owner, repo, pr_number)

        print("Fetching commit list ...", file=sys.stderr)
        commits = fetch_pr_commits(client, owner, repo, pr_number)

        maintainer_login = fetch_authenticated_user(client)

        # Phase 3 — rewrite paths
        result = rewrite_diff(raw_diff, package_name)

        if result.warnings:
            print(
                "warning: unrecognised root-level files kept in diff (requires review):",
                file=sys.stderr,
            )
            for w in result.warnings:
                print(f"  {w}", file=sys.stderr)

        pr_body = build_pr_body(
            old_pr_url=args.pr_url,
            maintainer_login=maintainer_login,
            contributor_login=contributor_login,
            original_body=original_body,
            package_name=package_name,
            original_base_ref=base_ref,
            dropped_files=result.dropped_files,
            warnings=result.warnings,
        )

        if args.dry_run:
            print("=== REWRITTEN DIFF ===\n")
            print(result.diff)
            print("\n=== DRAFT PR BODY ===\n")
            print(pr_body)
            return

        # Phase 4 — apply to monorepo
        branch_name = f"migrate/{package_name}/pr-{pr_number}"

        # Verify clean working tree.
        status = git(["status", "--porcelain"], cwd=monorepo_path)
        if status.stdout.strip():
            sys.exit(
                "error: monorepo working tree is not clean. "
                "Commit or stash your changes first."
            )

        # Fast-fail: check the full PR diff applies before creating the branch.
        check = apply_diff_text(result.diff, cwd=monorepo_path, check_only=True)
        if check.returncode != 0:
            patch_file = os.path.join(
                monorepo_path, f"{package_name}-pr-{pr_number}.patch"
            )
            with open(patch_file, "w") as fh:
                fh.write(result.diff)
            sys.exit(
                f"error: rewritten diff does not apply cleanly.\n"
                f"  Patch saved to: {patch_file}\n"
                f"  Resolve conflicts manually, then:\n"
                f"    git checkout -b {branch_name}\n"
                f"    git apply {patch_file}\n"
                f"  git output:\n{check.stderr}"
            )

        # Create branch.
        git(["checkout", "-b", branch_name], cwd=monorepo_path)

        # Apply each commit individually.
        print(f"Replaying {len(commits)} commit(s) on branch {branch_name} ...", file=sys.stderr)
        for i, commit in enumerate(commits, 1):
            sha = commit["sha"]
            commit_message = commit["commit"]["message"]
            author_name = commit["commit"]["author"]["name"]
            author_email = commit["commit"]["author"]["email"]
            author_date = commit["commit"]["author"]["date"]
            short_sha = sha[:7]
            short_msg = commit_message.splitlines()[0]

            print(f"  [{i}/{len(commits)}] {short_sha} {short_msg}", file=sys.stderr)

            commit_diff_raw = fetch_commit_diff(client, owner, repo, sha)
            commit_result = rewrite_diff(commit_diff_raw, package_name)

            if diff_is_empty(commit_result.diff):
                print(
                    f"    skipping {short_sha}: diff is empty after path rewriting "
                    f"(all files were dropped)",
                    file=sys.stderr,
                )
                continue

            apply_proc = apply_diff_text(commit_result.diff, cwd=monorepo_path)
            if apply_proc.returncode != 0:
                patch_file = os.path.join(
                    monorepo_path, f"{package_name}-pr-{pr_number}-{short_sha}.patch"
                )
                with open(patch_file, "w") as fh:
                    fh.write(commit_result.diff)
                sys.exit(
                    f"error: commit {short_sha} does not apply cleanly.\n"
                    f"  Patch saved to: {patch_file}\n"
                    f"  git output:\n{apply_proc.stderr}"
                )

            full_message = f"{commit_message}\n\nMigrated-from: {args.pr_url}"
            git(
                ["commit", "-m", full_message],
                cwd=monorepo_path,
                env={
                    "GIT_AUTHOR_NAME": author_name,
                    "GIT_AUTHOR_EMAIL": author_email,
                    "GIT_AUTHOR_DATE": author_date,
                    "GIT_LFS_SKIP_SMUDGE": "1",
                },
            )

        # Fetch LFS objects referenced by the PR head into the local cache so the
        # git-lfs pre-push hook can upload them to the target automatically.
        fetch_lfs_objects(owner, repo, head_sha, token, monorepo_path)

        # Push (git-lfs pre-push hook uploads any cached LFS objects).
        print(f"Pushing {branch_name} ...", file=sys.stderr)
        push_remote = push_url(remote_url, token)
        push_proc = git(
            ["push", "--force-with-lease", push_remote, branch_name],
            cwd=monorepo_path,
            check=False,
        )
        if push_proc.returncode != 0:
            sys.exit(
                f"error: git push failed.\n"
                f"  git stderr:\n{push_proc.stderr}"
            )

        # Phase 5 — open draft PR and notify.
        print("Opening draft PR on monorepo ...", file=sys.stderr)
        pr_resp = client.post(
            f"{GITHUB_API}/repos/{monorepo_owner}/{monorepo_repo}/pulls",
            json={
                "title": f"[migrated] {title}",
                "body": pr_body,
                "head": branch_name,
                "base": "master",
                "draft": True,
            },
        )
        pr_resp.raise_for_status()
        new_pr_url = pr_resp.json()["html_url"]
        print(f"Draft PR created: {new_pr_url}", file=sys.stderr)

        client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments",
            json={
                "body": (
                    f"This PR has been migrated to the dissect monorepo: {new_pr_url}\n\n"
                    f"The original diff and commit history have been preserved on the "
                    f"`migrate/{package_name}/pr-{pr_number}` branch."
                )
            },
        ).raise_for_status()
        print("Comment posted on original PR.", file=sys.stderr)

        print(f"\nDone! Review the draft and un-draft when ready: {new_pr_url}")


if __name__ == "__main__":
    main()
