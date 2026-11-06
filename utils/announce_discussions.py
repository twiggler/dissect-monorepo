#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Post the monorepo announcement as GitHub Discussions.

Usage:
    uv run utils/announce_discussions.py [--dry-run] [--main OWNER/REPO]
        [--body PATH] [--repo-list PATH]

Creates the main discussion, with the full announcement, on the --main repository, and a
short discussion on every other repository in --repo-list that links to it. The short
discussions are locked so that all replies go to the main discussion. Everything is
posted in the "Announcements" category.

The title is the "# " heading on the first line of --body; the rest of the file is the
body of the main discussion. Repositories that already have a discussion with that title
are left alone, so the script is safe to re-run after a partial failure. Repositories
with Discussions disabled are reported and skipped.

Always run with --dry-run first: it only reads from GitHub and prints what it would do.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

GITHUB_GRAPHQL = "https://api.github.com/graphql"
CATEGORY = "Announcements"
MONOREPO = "fox-it/dissect"

# Pause after every write call to stay clear of GitHub's secondary rate limits on
# content creation.
WRITE_DELAY = 2.0

POINTER_BODY = """\
The `dissect.*` repositories, including this one, are moving to a single monorepo: `{monorepo}`.

**Read the announcement and share your feedback here: {main_url}**

This discussion is locked to keep the conversation in one place.
"""

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id
    hasDiscussionsEnabled
    discussionCategories(first: 25) { nodes { id name } }
    discussions(first: 100) { nodes { id title url locked } }
  }
}
"""

CREATE_MUTATION = """
mutation($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {repositoryId: $repositoryId, categoryId: $categoryId, title: $title, body: $body}) {
    discussion { id url locked }
  }
}
"""

LOCK_MUTATION = """
mutation($id: ID!) {
  lockLockable(input: {lockableId: $id}) { lockedRecord { locked } }
}
"""


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
        "  Option 2: set the GITHUB_TOKEN environment variable"
    )


# ── GitHub API ────────────────────────────────────────────────────────────────


def graphql(client: httpx.Client, query: str, **variables: str) -> dict:
    resp = client.post(GITHUB_GRAPHQL, json={"query": query, "variables": variables})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        messages = "; ".join(error["message"] for error in payload["errors"])
        sys.exit(f"error: GitHub GraphQL request failed: {messages}")
    return payload["data"]


@dataclass(frozen=True)
class RepoState:
    name: str  # owner/repo
    id: str
    discussions_enabled: bool
    category_id: str | None  # id of the CATEGORY category, if the repository has one
    existing: dict | None  # discussion that already has the announcement title: {id, url, locked}

    def skip_reason(self) -> str | None:
        if not self.discussions_enabled:
            return "Discussions disabled"
        if self.category_id is None:
            return f"no {CATEGORY!r} category"
        return None


def fetch_repo_state(client: httpx.Client, name: str, title: str) -> RepoState:
    owner, repo_name = name.split("/", 1)
    repo = graphql(client, REPO_QUERY, owner=owner, name=repo_name)["repository"]
    categories = repo["discussionCategories"]["nodes"]
    discussions = repo["discussions"]["nodes"]
    return RepoState(
        name=name,
        id=repo["id"],
        discussions_enabled=repo["hasDiscussionsEnabled"],
        category_id=next((c["id"] for c in categories if c["name"] == CATEGORY), None),
        existing=next((d for d in discussions if d["title"] == title), None),
    )


def create_discussion(client: httpx.Client, state: RepoState, title: str, body: str) -> dict:
    data = graphql(
        client,
        CREATE_MUTATION,
        repositoryId=state.id,
        categoryId=state.category_id,
        title=title,
        body=body,
    )
    time.sleep(WRITE_DELAY)
    return data["createDiscussion"]["discussion"]


def lock_discussion(client: httpx.Client, discussion_id: str) -> None:
    graphql(client, LOCK_MUTATION, id=discussion_id)
    time.sleep(WRITE_DELAY)


# ── Input parsing ─────────────────────────────────────────────────────────────


def read_announcement(path: Path) -> tuple[str, str]:
    """Return (title, body): the '# ' heading on the first line, and the rest of the file."""
    first_line, _, rest = path.read_text().partition("\n")
    if not first_line.startswith("# "):
        sys.exit(f"error: {path} must start with a '# <title>' heading")
    return first_line.removeprefix("# ").strip(), rest.strip() + "\n"


def read_repo_list(path: Path) -> list[str]:
    """Return owner/repo names; accepts 'github.com:owner/repo' (as in migrate/project-list) and 'owner/repo'."""
    names = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.rpartition(":")[2])
    return names


# ── Main ──────────────────────────────────────────────────────────────────────


def report(name: str, action: str, url: str = "") -> None:
    print(f"  [{action}] {name} {url}".rstrip(), file=sys.stderr)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description=(
            "Post the monorepo announcement as a main discussion, plus a locked discussion "
            "linking to it on every other repository. Always run with --dry-run first."
        )
    )
    parser.add_argument(
        "--main",
        default="fox-it/dissect.target",
        metavar="OWNER/REPO",
        help="Repository for the main discussion (default: fox-it/dissect.target)",
    )
    parser.add_argument(
        "--body",
        default=repo_root / "announcement.md",
        type=Path,
        help="Announcement file; its first line is the '# <title>' heading (default: announcement.md)",
    )
    parser.add_argument(
        "--repo-list",
        default=repo_root / "migrate" / "project-list",
        type=Path,
        help="Repositories to post on, one per line (default: migrate/project-list)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only read from GitHub and print what would be done",
    )
    args = parser.parse_args()

    title, main_body = read_announcement(args.body)
    pointer_names = [name for name in read_repo_list(args.repo_list) if name != args.main]

    token = resolve_token()
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        # Phase 1 — read the state of every repository (read-only)
        print(f"Reading {len(pointer_names) + 1} repositories ...", file=sys.stderr)
        main_state = fetch_repo_state(client, args.main, title)
        pointer_states = [fetch_repo_state(client, name, title) for name in pointer_names]

        if reason := main_state.skip_reason():
            sys.exit(f"error: cannot post the main discussion on {args.main}: {reason}")

        # Phase 2 — main discussion
        print(f"\nMain discussion: {title!r}", file=sys.stderr)
        if main_state.existing:
            main_url = main_state.existing["url"]
            report(args.main, "exists", main_url)
        elif args.dry_run:
            main_url = "<main discussion URL>"
            report(args.main, "would create")
        else:
            main_url = create_discussion(client, main_state, title, main_body)["url"]
            report(args.main, "created", main_url)
        results = [(args.main, main_url)]

        # Phase 3 — locked pointer discussions on the other repositories
        pointer_body = POINTER_BODY.format(monorepo=MONOREPO, main_url=main_url)
        print("\nPointer discussions:", file=sys.stderr)
        for state in pointer_states:
            if reason := state.skip_reason():
                report(state.name, f"skipped: {reason}")
                continue

            discussion = state.existing
            if discussion:
                actions = ["exists"]
            elif args.dry_run:
                report(state.name, "would create + lock")
                continue
            else:
                discussion = create_discussion(client, state, title, pointer_body)
                actions = ["created"]

            if not discussion["locked"]:
                if args.dry_run:
                    actions.append("would lock")
                else:
                    lock_discussion(client, discussion["id"])
                    actions.append("locked")

            report(state.name, ", ".join(actions), discussion["url"])
            results.append((state.name, discussion["url"]))

    if args.dry_run:
        print("\n=== POINTER BODY ===\n")
        print(pointer_body)
        return

    print("\n=== DISCUSSIONS ===\n")
    for name, url in results:
        print(f"{name}\t{url}")


if __name__ == "__main__":
    main()
