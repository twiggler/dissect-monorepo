# utils/

Maintainer utilities for one-off operations. These scripts are not deployed to the monorepo.

> [!WARNING]
> These scripts are provided as-is for maintainer convenience. They make changes that
> are hard to reverse: creating branches, pushing to GitHub, and opening pull requests.
> Always run with `--dry-run` first and inspect the output carefully before running
> without it. The authors accept no liability for data loss, repository corruption,
> or any other damage resulting from use of these scripts.

## migrate_pr.py

Migrates an open pull request from a legacy per-package repository to the monorepo.
It shallow-clones the PR branch into a throwaway directory, rewrites all file paths to
the monorepo `src`-layout with `git filter-repo`, serialises the rewritten commits as a
patch mailbox, and applies them with `git am` onto a new branch in the monorepo
(preserving author, commit message, and timestamps), pushes the branch, opens a draft
PR, and posts a comment on the original PR.

### Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — used to run the script with its inline dependencies
- [`git-filter-repo`](https://github.com/newren/git-filter-repo) — path rewriting
  (`pip install git-filter-repo` or `apt/dnf install git-filter-repo`)
- GitHub auth: either the `gh` CLI (`gh auth login`) or a `GITHUB_TOKEN` environment
  variable with `repo` scope
- Write access to the monorepo

### Usage

```sh
# Always dry-run first — prints the file classification and draft PR body, no changes
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42 --dry-run

# Migrate for real (run from inside the monorepo checkout)
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42

# If you are not inside the monorepo, pass the path explicitly
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42 \
    --monorepo-path /path/to/monorepo
```

### What it does

1. Fetches PR metadata and the file list from the GitHub API.
2. Shallow-clones the PR branch (depth = number of commits + 1) into a temp directory.
3. Rewrites paths with `git filter-repo --filename-callback`:
   - `dissect/<subpkg>/...` → `projects/<package>/src/dissect/<subpkg>/...`
   - `tests/...` → `projects/<package>/tests/...`
   - `tox.ini`, `pyproject.toml` — dropped (replaced/heavily modified during migration)
   - Anything else — placed under `projects/<package>/` and flagged for review
   Also injects a `Migrated-from:` trailer into each commit message.
4. Creates a branch `migrate/<package>/pr-<N>`, serialises the rewritten commits as a
   patch mailbox with `git format-patch`, and applies it with `git am` (pure context
   matching — no 3-way merge). This works because the patches' context lines come from
   the rewritten source commits, which match the monorepo verbatim as long as the
   monorepo is up-to-date with the latest changes from the source repository.
5. Pushes the branch and opens a draft PR titled `[migrated] <original title>`.
6. Posts a comment on the original PR with a link to the new draft.

### After migration

The resulting PR is a **draft**. Review the diff, address any warnings noted in the
PR body, then mark it ready for review. The original PR can be closed once the
migrated one is merged.

### Git LFS files

LFS-tracked files are transferred automatically. The script adds the source repository
as a temporary git remote, runs `git lfs fetch` to pull the objects into the local
cache, then removes the remote. The standard git-lfs pre-push hook picks them up from
the cache during `git push` and uploads them to the target's LFS server.

No manual steps are required. If `git lfs fetch` encounters an error a warning is
printed, but the script continues — the branch and PR are still created.

### Avoiding conflicts

`git am` uses context matching (not a 3-way merge). The patches apply cleanly as long as
the files in the monorepo match the content of those files in the source repository at
the base of the PR. The simplest way to ensure this is to keep the monorepo up-to-date:
merge any recent changes from the source repository before running the script.

If `git am` fails anyway, the script aborts the patch series and exits with the
conflicting patch details. At that point you can either update the monorepo and re-run
the script on a freshly reset branch, or apply the patch manually and continue with
`git am --continue`.
