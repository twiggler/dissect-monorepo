#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Migrate a PR from a per-project repo to the dissect monorepo.

Usage:
    uv run utils/migrate_pr.py <pr-url> [--target URL] [--monorepo-path PATH] [--dry-run]

The PR is squashed into one commit holding the changes GitHub shows under "Files changed",
with the paths rewritten to the monorepo layout. The commit is made on top of the target's
main branch without touching the working tree of the checkout.

The branch is always pushed to the `origin` remote of the checkout, and the PR is always
opened on the target (--target, default: the monorepo):

- Fork mode (origin is your fork of the target): no write access to the monorepo is
  needed, so PR authors can migrate their own PRs and keep pushing to them.
- Maintainer mode (origin is the target itself).

Always run with --dry-run first: it shows the commit and the draft PR body and checks that
the changes apply, without pushing or creating anything.
"""

import argparse
import base64
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

GITHUB_API = "https://api.github.com"

# The monorepo. The original PR only gets a "migrated" comment when the target is this repo,
# so test runs against a copy never comment on real PRs.
MONOREPO_URL = "https://github.com/fox-it/dissect"
# The repository migrated PRs are opened on. Switch to MONOREPO_URL at go-live; until then
# that is still the legacy meta-package repo.
DEFAULT_TARGET = "https://github.com/twiggler/dissect-monorepo-test"
# The monorepo's only branch (see migrate/overwrite_remote.sh).
MONOREPO_BRANCH = "main"

# Paths of the old per-project repos that migrate/migrate.sh does not carry over, or that the
# monorepo replaced. Changes to them are dropped and noted in the PR body.
#
# tox.ini                — superseded by the `just` recipes.
# .github                — CI lives in the monorepo root.
# .gitignore             — consolidated into the monorepo root .gitignore.
# .git-blame-ignore-revs — merged into the monorepo root file, with rewritten commit ids.
# tests/_docs/Makefile   — the monorepo calls sphinx-build directly.
# pyproject.toml         — kept, but heavily edited during migration (build backend, dependency
#                          groups, tool config); old per-project changes would conflict or be wrong.
DROP_PATHS = ("tox.ini", ".github", ".gitignore", ".git-blame-ignore-revs", "tests/_docs/Makefile", "pyproject.toml")

CO_AUTHOR_RE = re.compile(r"^co-authored-by:\s*(.+?)\s*<([^>]+)>\s*$", re.IGNORECASE | re.MULTILINE)


# ── Auth ──────────────────────────────────────────────────────────────────────


def resolve_token() -> str:
    if shutil.which("gh"):
        status = subprocess.run(["gh", "auth", "status"], capture_output=True)
        if status.returncode == 0:
            result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
            token = result.stdout.strip()
            if token:
                return token

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token

    sys.exit(
        "error: no GitHub token found.\n"
        "  Option 1: run `gh auth login` (gh CLI)\n"
        "  Option 2: set the GITHUB_TOKEN environment variable to a classic token with `repo` scope\n"
        "            (fine-grained tokens cannot open PRs on repositories owned by someone else)"
    )


def git_auth_env(token: str) -> dict[str, str]:
    """Return environment variables that make git and git-lfs authenticate to GitHub with the token.

    The token travels in an HTTP header set through GIT_CONFIG_* variables instead of in a
    URL, so it never appears in command lines, error messages or remote configuration.
    """
    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credentials}",
    }


# ── GitHub API ────────────────────────────────────────────────────────────────


def api(client: httpx.Client, method: str, path: str, **kwargs: object) -> httpx.Response:
    """Call the GitHub API and exit with GitHub's error message if the call fails.

    path is relative to the API root, or a full URL such as a pagination link.
    """
    url = path if path.startswith("https://") else f"{GITHUB_API}{path}"
    resp = client.request(method, url, **kwargs)
    if resp.is_error:
        try:
            body = resp.json()
            detail = " ".join(filter(None, [body.get("message"), str(body.get("errors") or "")]))
        except ValueError:
            detail = resp.text
        sys.exit(f"error: GitHub API {method} {path} returned {resp.status_code}: {detail}")
    return resp


def api_get(client: httpx.Client, path: str) -> httpx.Response:
    return api(client, "GET", path)


def api_get_all(client: httpx.Client, path: str) -> list[dict]:
    """GET every page of a list endpoint; GitHub returns 30 items per page by default."""
    items: list[dict] = []
    url: str | None = f"{path}?per_page=100"
    while url:
        resp = api_get(client, url)
        items += resp.json()
        url = resp.links.get("next", {}).get("url")
    return items


def fetch_pr(client: httpx.Client, owner: str, repo: str, pr_number: int) -> dict:
    return api_get(client, f"/repos/{owner}/{repo}/pulls/{pr_number}").json()


def fetch_pr_commits(client: httpx.Client, owner: str, repo: str, pr_number: int) -> list[dict]:
    return api_get_all(client, f"/repos/{owner}/{repo}/pulls/{pr_number}/commits")


def fetch_merge_base(client: httpx.Client, owner: str, repo: str, base_ref: str, head_sha: str) -> str:
    """Return the commit GitHub diffs the PR head against under "Files changed"."""
    compare = api_get(client, f"/repos/{owner}/{repo}/compare/{base_ref}...{head_sha}?per_page=1").json()
    return compare["merge_base_commit"]["sha"]


def fetch_repo(client: httpx.Client, owner: str, repo: str) -> dict:
    return api_get(client, f"/repos/{owner}/{repo}").json()


def fetch_authenticated_user(client: httpx.Client) -> str:
    return api_get(client, "/user").json()["login"]


def is_user_account(client: httpx.Client, login: str) -> bool:
    """Return False for organisations. "Allow edits by maintainers" only works on forks owned by a user."""
    return api_get(client, f"/users/{login}").json()["type"] == "User"


# ── Path classification ───────────────────────────────────────────────────────


def classify_path(path: str) -> str:
    """Return 'rewrite', 'drop', or 'warn' for a file path from the old repo."""
    if any(path == dropped or path.startswith(f"{dropped}/") for dropped in DROP_PATHS):
        return "drop"
    if path.startswith(("dissect/", "tests/")):
        return "rewrite"
    return "warn"


# ── Git helpers ───────────────────────────────────────────────────────────────


def git(
    args: list[str],
    *,
    cwd: str | Path,
    env: dict | None = None,
    input: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run git; if check is set and git fails, exit with the command and git's error output.

    Output is decoded with surrogateescape, so patches that are not valid UTF-8 survive the
    round trip from one git command to the next unchanged.
    """
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        input=input,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if check and proc.returncode != 0:
        sys.exit(f"error: `git {shlex.join(args)}` failed:\n{proc.stderr.rstrip()}")
    return proc


def get_remote_url(cwd: str | Path) -> str:
    return git(["remote", "get-url", "origin"], cwd=cwd).stdout.strip()


def parse_remote_url(url: str) -> tuple[str, str]:
    m = re.match(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"https://(?:[^@]+@)?github\.com/([^/]+)/(.+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1), m.group(2)
    sys.exit(f"error: cannot parse GitHub repository URL: {url!r}")


def github_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


# ── Squashing ─────────────────────────────────────────────────────────────────
#
# The PR is migrated as the diff between its merge base and its head, which is what
# GitHub shows under "Files changed". Replaying the individual commits does not work for
# PRs that merged the base branch into their branch (about a third of them): the merged
# commits would be replayed too, and conflict resolutions in merge commits would be lost.


def fetch_source(tmp_dir: str, owner: str, repo: str, merge_base: str, head_sha: str, auth: dict[str, str]) -> None:
    """Fetch just the merge base and the head of the PR into a bare throwaway repository.

    Nothing is checked out: a checkout would download every LFS file in the tree, and it
    fails outright when git-lfs cannot tell where to download from.
    """
    git(["init", "--bare", tmp_dir], cwd=tmp_dir)
    git(["remote", "add", "source", github_url(owner, repo)], cwd=tmp_dir)
    git(["fetch", "--depth", "1", "source", merge_base, head_sha], cwd=tmp_dir, env=auth)


def mktree(entries: list[str], cwd: str) -> str:
    return git(["mktree", "-z"], cwd=cwd, input="".join(f"{entry}\0" for entry in entries)).stdout.strip()


def rewrite_tree(commit: str, package_name: str, cwd: str) -> str:
    """Return a tree with the commit's files at their monorepo paths.

    dissect/ moves to projects/<package>/src/dissect/, everything else to projects/<package>/.
    """
    entries = []
    for entry in git(["ls-tree", "-z", commit], cwd=cwd).stdout.split("\0"):
        if not entry:
            continue
        if entry.partition("\t")[2] == "dissect":
            entry = f"040000 tree {mktree([entry], cwd)}\tsrc"
        entries.append(entry)
    for directory in (package_name, "projects"):
        entries = [f"040000 tree {mktree(entries, cwd)}\t{directory}"]
    return mktree(entries, cwd)


def changed_files(base: str, head: str, cwd: str) -> dict[str, str]:
    """Return {path: status letter (A, M, D, ...)} for the files that differ between two commits."""
    fields = git(["diff-tree", "-r", "-z", "--no-renames", "--name-status", base, head], cwd=cwd).stdout.split("\0")
    return dict(zip(fields[1::2], fields[0::2], strict=False))


def changed_lfs_objects(head: str, changed: dict[str, str], cwd: str) -> dict[str, str]:
    """Return {path: LFS object id} for the LFS files the PR adds or modifies."""
    objects = {}
    for line in git(["lfs", "ls-files", "--long", head], cwd=cwd).stdout.splitlines():
        oid, _, path = line.split(" ", 2)
        if changed.get(path, "D") != "D":
            objects[path] = oid
    return objects


def squash_commit_metadata(title: str, commits: list[dict], pr_author: str, pr_url: str) -> tuple[str, dict[str, str]]:
    """Return the message and the author environment variables for the squashed commit.

    The author is the PR author, with the name and email from their own commits. Everyone
    else with commits in the PR, or credited in a Co-authored-by trailer, becomes a
    co-author. The body lists the original commit messages, as GitHub's squash merge does.
    """
    author = next((c for c in commits if (c["author"] or {}).get("login") == pr_author), commits[0])
    author = author["commit"]["author"]

    co_authors: dict[str, str] = {}
    entries = []
    for c in commits:
        commit_author = c["commit"]["author"]
        co_authors.setdefault(commit_author["email"].lower(), f"{commit_author['name']} <{commit_author['email']}>")
        for name, email in CO_AUTHOR_RE.findall(c["commit"]["message"]):
            co_authors.setdefault(email.lower(), f"{name} <{email}>")
        subject, _, body = CO_AUTHOR_RE.sub("", c["commit"]["message"]).strip().partition("\n")
        entries.append(f"* {subject}" + (f"\n\n{body.strip()}" if body.strip() else ""))
    co_authors.pop(author["email"].lower(), None)

    separator = "\n\n" if any("\n" in entry for entry in entries) else "\n"
    trailers = [f"Co-authored-by: {co_author}" for co_author in co_authors.values()]
    trailers.append(f"Migrated-from: {pr_url}")
    message = f"{title}\n\n{separator.join(entries)}\n\n" + "\n".join(trailers) + "\n"
    author_env = {
        "GIT_AUTHOR_NAME": author["name"],
        "GIT_AUTHOR_EMAIL": author["email"],
        "GIT_AUTHOR_DATE": commits[-1]["commit"]["author"]["date"],
    }
    return message, author_env


# ── PR body ───────────────────────────────────────────────────────────────────


def build_pr_body(
    *,
    old_pr_url: str,
    migrated_by: str,
    contributor_login: str,
    original_body: str,
    package_name: str,
    original_base_ref: str,
    num_commits: int,
    dropped_files: list[str],
    warnings: list[str],
) -> str:
    if migrated_by == contributor_login:
        origin_note = f"> Migrated from {old_pr_url} by its author, @{contributor_login}.\n"
    else:
        origin_note = f"> Migrated from {old_pr_url} by @{migrated_by}.\n> Original author: @{contributor_login}\n"

    squash_section = ""
    if num_commits > 1:
        squash_section = f"\n- The {num_commits} original commits were squashed into one, which lists their messages."

    dropped_section = ""
    if dropped_files:
        files = ", ".join(f"`{f}`" for f in dropped_files)
        dropped_section = (
            f"\n- Changes to these files were not migrated, because the monorepo dropped or replaced them: {files}"
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
        f"{origin_note}"
        f"\n---\n\n"
        f"{body}\n"
        f"\n---\n\n"
        f"**Migration notes**\n\n"
        f"- Project: `{package_name}`\n"
        f"- Original base branch: `{original_base_ref}`"
        f"{squash_section}"
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
            "Migrate a GitHub PR from a per-project repo to the dissect monorepo. "
            "Run from a clone of your fork of the monorepo (fork mode), or from a clone of the "
            "monorepo itself if you have write access (maintainer mode). "
            "Always run with --dry-run first."
        )
    )
    parser.add_argument("pr_url", metavar="PR_URL", help="Full GitHub URL of the PR to migrate")
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"GitHub URL of the repository to open the PR on (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--monorepo-path",
        default=".",
        help="Path to a clone of the monorepo or of your fork of it (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the commit and draft PR body and check that the changes apply; push and create nothing",
    )
    args = parser.parse_args()

    if subprocess.run(["git", "lfs", "version"], capture_output=True).returncode != 0:
        sys.exit("error: git-lfs is required but not installed. See https://git-lfs.com.")

    monorepo_path = Path(args.monorepo_path).resolve()

    # Phase 1 — inputs and inference
    owner, repo, pr_number = parse_pr_url(args.pr_url)
    package_name = normalize_package_name(repo)
    origin_owner, origin_repo = parse_remote_url(get_remote_url(monorepo_path))
    target_owner, target_repo = parse_remote_url(args.target)
    fork_mode = (origin_owner.lower(), origin_repo.lower()) != (target_owner.lower(), target_repo.lower())
    targets_monorepo = (target_owner.lower(), target_repo.lower()) == parse_remote_url(MONOREPO_URL)

    branch_name = f"migrate/{package_name}/pr-{pr_number}"
    if git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}"], cwd=monorepo_path, check=False).stdout:
        sys.exit(f"error: branch {branch_name} already exists. Delete it to migrate the PR again.")

    token = resolve_token()
    auth = git_auth_env(token)
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
        if pr_data["merged_at"]:
            sys.exit(f"error: {args.pr_url} is already merged, so its changes are part of the monorepo.")

        # Closed PRs and archived repositories can still be migrated: everything the script
        # reads stays available. Only the comment on the original PR is not possible then.
        comment = targets_monorepo
        if not targets_monorepo:
            print(f"Note: the target is not {MONOREPO_URL}; the original PR gets no comment.", file=sys.stderr)
        elif fetch_repo(client, owner, repo)["archived"]:
            comment = False
            print(f"Note: {owner}/{repo} is archived; the original PR gets no comment.", file=sys.stderr)

        print("Fetching commit list ...", file=sys.stderr)
        # Merges of the base branch into the PR branch bring in no changes of the PR's own.
        commits = [c for c in fetch_pr_commits(client, owner, repo, pr_number) if len(c["parents"]) == 1]
        if not commits:
            sys.exit(f"error: {args.pr_url} consists of merge commits only; there is nothing to migrate.")
        merge_base = fetch_merge_base(client, owner, repo, base_ref, head_sha)
        message, author_env = squash_commit_metadata(title, commits, contributor_login, args.pr_url)

        migrated_by = fetch_authenticated_user(client)

        if fork_mode:
            maintainer_can_modify = is_user_account(client, origin_owner)
            print(
                f"Fork mode: pushing to {origin_owner}/{origin_repo}, opening PR on {target_owner}/{target_repo}",
                file=sys.stderr,
            )
        else:
            maintainer_can_modify = False
            print(f"Maintainer mode: pushing to and opening PR on {target_owner}/{target_repo}", file=sys.stderr)

        with tempfile.TemporaryDirectory(prefix="migrate_pr_") as tmp_dir:
            # Phase 3 — squash the PR and rewrite its paths
            print("Fetching the PR's merge base and head ...", file=sys.stderr)
            fetch_source(tmp_dir, owner, repo, merge_base, head_sha, auth)
            changed = changed_files(merge_base, head_sha, tmp_dir)
            dropped_files = sorted(p for p in changed if classify_path(p) == "drop")
            warnings = sorted(p for p in changed if classify_path(p) == "warn")
            patch = git(
                [
                    "diff-tree",
                    "-p",
                    "--binary",
                    "-M",
                    rewrite_tree(merge_base, package_name, tmp_dir),
                    rewrite_tree(head_sha, package_name, tmp_dir),
                    "--",
                    *(f":(exclude)projects/{package_name}/{dropped}" for dropped in DROP_PATHS),
                ],
                cwd=tmp_dir,
            ).stdout
            if not patch:
                sys.exit(f"error: nothing to migrate; the PR only changes files that are not migrated: {dropped_files}")
            lfs_objects = changed_lfs_objects(head_sha, changed, tmp_dir)

            if warnings:
                print(
                    f"warning: unrecognised root-level files will be placed under projects/{package_name}/:",
                    file=sys.stderr,
                )
                for w in warnings:
                    print(f"  {w}", file=sys.stderr)

            # Phase 4 — commit the changes on top of the target's main. They are applied in a
            # temporary index, so the working tree and the current branch stay as they are.
            print(f"Fetching {MONOREPO_BRANCH} from {target_owner}/{target_repo} ...", file=sys.stderr)
            git(["fetch", github_url(target_owner, target_repo), MONOREPO_BRANCH], cwd=monorepo_path, env=auth)
            parent = git(["rev-parse", "FETCH_HEAD"], cwd=monorepo_path).stdout.strip()
            index = {"GIT_INDEX_FILE": str(Path(tmp_dir) / "index")}
            git(["read-tree", parent], cwd=monorepo_path, env=index)
            applied = git(
                ["apply", "--cached", "--whitespace=nowarn"], cwd=monorepo_path, env=index, input=patch, check=False
            )
            if applied.returncode != 0:
                patch_file = Path(tempfile.gettempdir()) / f"migrate_pr_{package_name}_pr-{pr_number}.patch"
                patch_file.write_text(patch, encoding="utf-8", errors="surrogateescape")
                sys.exit(
                    f"error: the PR's changes do not apply to {target_owner}/{target_repo}@{MONOREPO_BRANCH}:\n"
                    f"{applied.stderr.rstrip()}\n\n"
                    f"The patch is saved as {patch_file}. Usually the PR is based on an old commit; merge\n"
                    f"the latest default branch of {owner}/{repo} into it (GitHub's 'Update branch') and retry."
                )
            tree = git(["write-tree"], cwd=monorepo_path, env=index).stdout.strip()
            commit = git(
                ["commit-tree", tree, "-p", parent, "-F", "-"], cwd=monorepo_path, env=author_env, input=message
            ).stdout.strip()

            pr_body = build_pr_body(
                old_pr_url=args.pr_url,
                migrated_by=migrated_by,
                contributor_login=contributor_login,
                original_body=original_body,
                package_name=package_name,
                original_base_ref=base_ref,
                num_commits=len(commits),
                dropped_files=dropped_files,
                warnings=warnings,
            )

            if args.dry_run:
                print("\n=== FILES ===\n")
                for path in sorted(changed):
                    print(f"  [{classify_path(path):7}] {path}")
                if lfs_objects:
                    print("\n=== LFS FILES ===\n")
                    for path in lfs_objects:
                        print(f"  {path}")
                print("\n=== COMMIT ===\n")
                print(git(["show", "--stat", "--no-color", "--format=fuller", commit], cwd=monorepo_path).stdout)
                print("=== DRAFT PR BODY ===\n")
                print(pr_body)
                print(
                    f"Dry run: the changes apply to {target_owner}/{target_repo}@{MONOREPO_BRANCH}. Nothing was pushed."
                )
                return

            if lfs_objects:
                # Download only the LFS files the PR changes, straight into the clone's LFS store.
                print(f"Fetching {len(lfs_objects)} LFS file(s) from {owner}/{repo} ...", file=sys.stderr)
                git_dir = git(["rev-parse", "--git-common-dir"], cwd=monorepo_path).stdout.strip()
                lfs_storage = (monorepo_path / git_dir / "lfs").resolve()
                git(
                    [
                        *("-c", f"lfs.storage={lfs_storage}", "lfs", "fetch"),
                        *(f"--include={','.join(lfs_objects)}", "source", head_sha),
                    ],
                    cwd=tmp_dir,
                    env=auth,
                )

        # Phase 5 — push
        git(["branch", branch_name, commit], cwd=monorepo_path)
        print(f"Pushing {branch_name} to {origin_owner}/{origin_repo} ...", file=sys.stderr)
        if lfs_objects:
            git(["lfs", "push", "--object-id", "origin", *lfs_objects.values()], cwd=monorepo_path, env=auth)
        # --no-verify skips the git-lfs pre-push hook. The PR's LFS files were pushed above,
        # and the hook would also look for those of commits on main that origin lacks (a fork
        # that lags behind), which this clone does not necessarily have.
        git(["push", "--no-verify", "--set-upstream", "origin", branch_name], cwd=monorepo_path, env=auth)

        # Phase 6 — open draft PR and notify.
        print(f"Opening draft PR on {target_owner}/{target_repo} ...", file=sys.stderr)
        pr_payload = {
            "title": f"[migrated] {title}",
            "body": pr_body,
            "head": f"{origin_owner}:{branch_name}" if fork_mode else branch_name,
            "base": MONOREPO_BRANCH,
            "draft": True,
        }
        if maintainer_can_modify:
            pr_payload["maintainer_can_modify"] = True
        pr_resp = api(client, "POST", f"/repos/{target_owner}/{target_repo}/pulls", json=pr_payload)
        new_pr_url = pr_resp.json()["html_url"]
        print(f"Draft PR created: {new_pr_url}", file=sys.stderr)

        if comment:
            api(
                client,
                "POST",
                f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
                json={"body": f"This PR has been migrated to the dissect monorepo: {new_pr_url}"},
            )
            print("Comment posted on original PR.", file=sys.stderr)

        print(f"\nDone! Review the draft and un-draft when ready: {new_pr_url}")


if __name__ == "__main__":
    main()
