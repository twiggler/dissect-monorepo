#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Migrate an open PR from a per-package repo to the dissect monorepo.

Usage:
    uv run utils/migrate_pr.py <pr-url> [--monorepo-path PATH] [--dry-run]

Always run with --dry-run first to inspect the draft PR body before making any changes.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

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


def fetch_pr_commits(
    client: httpx.Client, owner: str, repo: str, pr_number: int
) -> list[dict]:
    return api_get(client, f"/repos/{owner}/{repo}/pulls/{pr_number}/commits").json()


def fetch_pr_files(
    client: httpx.Client, owner: str, repo: str, pr_number: int
) -> list[str]:
    """Return the list of filenames changed by the PR."""
    return [
        f["filename"]
        for f in api_get(client, f"/repos/{owner}/{repo}/pulls/{pr_number}/files").json()
    ]


def fetch_authenticated_user(client: httpx.Client) -> str:
    return api_get(client, "/user").json()["login"]


# ── Path classification ───────────────────────────────────────────────────────


def classify_path(path: str) -> str:
    """Return 'rewrite', 'drop', or 'warn' for a file path from the old repo."""
    if re.match(r"^dissect/", path):
        return "rewrite"
    if re.match(r"^tests/", path):
        return "rewrite"
    if path in DROP_FILES:
        return "drop"
    return "warn"


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
        # Fetch git objects first so `git lfs fetch` can call `git ls-tree` on the SHA.
        git(["fetch", remote_name, head_sha], cwd=cwd, check=False)
        proc = git(["lfs", "fetch", remote_name, "FETCH_HEAD"], cwd=cwd, check=False)
        if proc.returncode != 0:
            print(f"warning: git lfs fetch incomplete:\n{proc.stderr}", file=sys.stderr)
    finally:
        git(["remote", "remove", remote_name], cwd=cwd)


# ── Migration ─────────────────────────────────────────────────────────────────


def migrate_commits(
    source_owner: str,
    source_repo: str,
    pr_number: int,
    num_commits: int,
    package_name: str,
    pr_url: str,
    token: str,
    monorepo_path: str,
) -> None:
    """Rewrite PR commits with git-filter-repo and apply them onto the current branch.

    Uses a temporary clone so no persistent state is left behind.

    Path rewriting is done by git-filter-repo which handles all diff edge cases
    (renames, binary files, LFS pointers, mode changes) correctly by operating on
    git objects rather than diff text.

    git-am applies each commit as a patch (context matching). Cherry-pick is NOT used
    because its 3-way merge base (boundary_sha, with source-repo paths) differs from
    monorepo HEAD (monorepo paths), causing spurious conflicts on every patched file.
    """
    source_url = f"https://x-access-token:{token}@github.com/{source_owner}/{source_repo}.git"

    with tempfile.TemporaryDirectory(prefix="migrate_pr_") as tmp_dir:
        # 1. Shallow-fetch the PR commits into a throwaway repo.
        #    depth = num_commits + 1 so the parent of the first PR commit is available
        #    as the base for cherry-pick's 3-way merge.
        print("Fetching PR commits ...", file=sys.stderr)
        subprocess.run(["git", "init", tmp_dir], check=True, capture_output=True)
        git(
            [
                "fetch", "--depth", str(num_commits + 1),
                source_url, f"refs/pull/{pr_number}/head",
            ],
            cwd=tmp_dir,
        )
        git(["checkout", "FETCH_HEAD"], cwd=tmp_dir)

        # 2. Rewrite paths and inject Migrated-from trailer with filter-repo.
        #
        # Path rules (--filename-callback):
        #   dissect/...     → projects/<pkg>/src/dissect/...   (source files)
        #   tests/...       → projects/<pkg>/tests/...          (test files)
        #   tox.ini         → dropped
        #   pyproject.toml  → dropped
        #   anything else   → projects/<pkg>/<original>         (warned in PR body)
        filename_cb = textwrap.dedent(f"""\
            if filename.startswith(b"dissect/"):
                return b"projects/{package_name}/src/" + filename
            elif filename.startswith(b"tests/"):
                return b"projects/{package_name}/" + filename
            elif filename in (b"tox.ini", b"pyproject.toml"):
                return None
            else:
                return b"projects/{package_name}/" + filename
        """)

        message_cb = textwrap.dedent(f"""\
            message = message.rstrip()
            if b"Migrated-from:" not in message:
                message = message + b"\\n\\nMigrated-from: {pr_url}"
            return message
        """)

        proc = subprocess.run(
            [
                "git", "filter-repo", "--force",
                "--filename-callback", filename_cb,
                "--message-callback", message_cb,
            ],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            sys.exit(f"error: git filter-repo failed:\n{proc.stderr}")

        # 3. Serialize the rewritten commits as a patch mailbox.
        #    format-patch encodes all content types (text, binary, LFS pointers) safely.
        #    The mailbox includes author name/email/date and the full commit message.
        patches = git(
            ["format-patch", "--stdout", f"HEAD~{num_commits}..HEAD"],
            cwd=tmp_dir,
        )
        if not patches.stdout.strip():
            print(
                "warning: all commits became empty after path rewriting "
                "(only dropped files were changed). Nothing to apply.",
                file=sys.stderr,
            )
            return

        # 4. Apply the patch series to the monorepo.
        #    Pure context matching (no --3way): the patches are generated from the
        #    *rewritten* source commits, so their context lines reflect the current
        #    state of files in the source repo.  Because migration preserved file
        #    content verbatim, those context lines match what is in the monorepo —
        #    even if the source repo has advanced since migration, the monorepo files
        #    at the affected paths have not changed (only the source repo did).
        #
        #    --3way is intentionally omitted: it would use boundary_sha's blobs as
        #    the merge base, but the monorepo is behind boundary_sha (migration was
        #    done at an earlier point), causing spurious conflicts on every file the
        #    source repo touched between migration and the PR base.
        #
        #    --committer-date-is-author-date preserves the original commit timestamps.
        print("Applying rewritten commits ...", file=sys.stderr)
        am_proc = subprocess.run(
            ["git", "am", "--committer-date-is-author-date"],
            input=patches.stdout,
            cwd=monorepo_path,
            env={**os.environ},
            capture_output=True,
            text=True,
        )
        if am_proc.returncode != 0:
            subprocess.run(["git", "am", "--abort"], cwd=monorepo_path, capture_output=True)
            sys.exit(
                f"error: git am failed (patch does not apply cleanly).\n"
                f"  git output:\n{am_proc.stderr}"
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
            f"\n- The following root-level files were placed under"
            f" `projects/{package_name}/` and require maintainer review: {files}"
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
        help="Print the file classification and draft PR body; make no changes",
    )
    args = parser.parse_args()

    # Check for required external tools.
    if subprocess.run(["git", "filter-repo", "--version"], capture_output=True).returncode != 0:
        sys.exit(
            "error: git-filter-repo is required but not installed.\n"
            "  pip install git-filter-repo\n"
            "  or: apt/dnf/brew install git-filter-repo"
        )

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
        # Phase 2 — fetch PR metadata
        print(f"Fetching PR data for {args.pr_url} ...", file=sys.stderr)
        pr_data = fetch_pr(client, owner, repo, pr_number)
        title = pr_data["title"]
        original_body = pr_data.get("body") or ""
        contributor_login = pr_data["user"]["login"]
        base_ref = pr_data["base"]["ref"]
        head_sha = pr_data["head"]["sha"]

        print("Fetching commit list ...", file=sys.stderr)
        commits = fetch_pr_commits(client, owner, repo, pr_number)
        num_commits = len(commits)

        print("Fetching file list ...", file=sys.stderr)
        filenames = fetch_pr_files(client, owner, repo, pr_number)
        dropped_files = [p for p in filenames if classify_path(p) == "drop"]
        warnings = [p for p in filenames if classify_path(p) == "warn"]

        maintainer_login = fetch_authenticated_user(client)

        if warnings:
            print(
                f"warning: unrecognised root-level files will be placed under"
                f" projects/{package_name}/:",
                file=sys.stderr,
            )
            for w in warnings:
                print(f"  {w}", file=sys.stderr)

        pr_body = build_pr_body(
            old_pr_url=args.pr_url,
            maintainer_login=maintainer_login,
            contributor_login=contributor_login,
            original_body=original_body,
            package_name=package_name,
            original_base_ref=base_ref,
            dropped_files=dropped_files,
            warnings=warnings,
        )

        if args.dry_run:
            print("\n=== FILE CLASSIFICATION ===\n")
            for filename in filenames:
                action = classify_path(filename)
                print(f"  [{action:7}] {filename}")
            print("\n=== DRAFT PR BODY ===\n")
            print(pr_body)
            return

        # Phase 3 — apply to monorepo
        branch_name = f"migrate/{package_name}/pr-{pr_number}"

        # Verify clean working tree.
        status = git(["status", "--porcelain"], cwd=monorepo_path)
        if status.stdout.strip():
            sys.exit(
                "error: monorepo working tree is not clean. "
                "Commit or stash your changes first."
            )

        # Create the migration branch.
        git(["checkout", "-b", branch_name], cwd=monorepo_path)

        # Rewrite paths with filter-repo and apply onto branch.
        migrate_commits(
            source_owner=owner,
            source_repo=repo,
            pr_number=pr_number,
            num_commits=num_commits,
            package_name=package_name,
            pr_url=args.pr_url,
            token=token,
            monorepo_path=monorepo_path,
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

        # Phase 4 — open draft PR and notify.
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
