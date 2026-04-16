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
It fetches the PR diff from the GitHub API, rewrites all file paths to the monorepo
`src`-layout, replays each original commit individually (preserving author and commit
message), pushes a branch, opens a draft PR on the monorepo, and posts a comment on
the original PR linking to the new one.

### Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — used to run the script with its inline dependencies
- GitHub auth: either the `gh` CLI (`gh auth login`) or a `GITHUB_TOKEN` environment
  variable with `repo` scope
- Write access to the monorepo

### Usage

```sh
# Always dry-run first — prints the rewritten diff and draft PR body, makes no changes
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42 --dry-run

# Migrate for real (run from inside the monorepo checkout)
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42

# If you are not inside the monorepo, pass the path explicitly
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42 \
    --monorepo-path /path/to/monorepo
```

### What it does

1. Fetches the PR metadata, full diff, and per-commit diffs from the GitHub API.
2. Rewrites all file paths to the monorepo layout under `projects/<package>/`:
   - `dissect/<subpkg>/...` → `projects/<package>/src/dissect/<subpkg>/...`
   - `tests/...` → `projects/<package>/tests/...`
   - `tox.ini`, `pyproject.toml` — dropped (replaced/heavily modified during migration)
   - Anything else at the repo root — kept and flagged for review
3. Verifies the rewritten diff applies cleanly before touching any branches.
4. Creates a branch `migrate/<package>/pr-<N>` and replays each original commit,
   preserving the original author name, email, and commit message, with a
   `Migrated-from:` trailer appended.
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

### When the patch does not apply cleanly

If the rewritten diff cannot be applied, the script saves the patch to
`<package>-pr-<N>.patch` in the monorepo root, prints instructions for manual
resolution, and exits without creating a branch. Resolve the conflicts in the patch
file and apply it manually following the printed instructions.
