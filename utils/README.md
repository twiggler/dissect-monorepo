# utils/

Utilities for one-off operations. These scripts are not deployed to the monorepo.

> [!WARNING]
> These scripts are provided as-is. They make changes that
> are hard to reverse: creating branches, pushing to GitHub, and opening pull requests.
> Always run with `--dry-run` first and inspect the output carefully before running
> without it. The authors accept no liability for data loss, repository corruption,
> or any other damage resulting from use of these scripts.

## migrate_pr.py

Migrates a pull request from a legacy per-project repository to the monorepo. It squashes
the PR into one commit with the paths rewritten to the monorepo layout, creates that commit
on a new branch, pushes the branch, opens a draft PR on the monorepo, and posts a comment
on the original PR.

The PR may be open or closed, and the legacy repository may be archived. Merged PRs are
refused: their changes are already part of the monorepo.

### Workflow

1. After go-live, PR authors migrate their own PRs in fork mode.
2. Before archiving the legacy repositories, maintainers close the PRs that are still
   open, with a comment explaining how to migrate them. This has to happen first:
   PRs in an archived repository can no longer be closed and would stay open forever.
3. Authors can still migrate a closed PR afterwards, also once its repository is
   archived. Maintainers can migrate a PR in maintainer mode at any time, for example
   when its author has gone quiet.

For step 2, list the open PRs first by running only the `gh pr list` command. If the
monorepo takes over one of the legacy repositories, leave that one out.

```sh
SCRIPT=https://github.com/twiggler/dissect-monorepo/raw/master/utils/migrate_pr.py
for repo in $(sed 's/^github\.com://' migrate/project-list); do
  for url in $(gh pr list --repo "$repo" --state open --limit 1000 --json url --jq '.[].url'); do
    gh pr close "$url" --comment "This repository has moved to the dissect monorepo and will be archived. \
To continue this PR there, run this from a clone of your fork of the monorepo:

    uv run $SCRIPT $url

See https://github.com/twiggler/dissect-monorepo/blob/master/utils/README.md for details."
  done
done
```

### Modes

The script pushes the branch to the `origin` remote of the clone it runs in, and opens
the PR on the monorepo. `--target` overrides the monorepo URL, for example to test
against a copy of the monorepo. The mode follows from comparing the two:

| `origin` is | Mode | Who can push to the migrated PR |
|---|---|---|
| your fork of the monorepo | fork mode | the fork owner, and maintainers if the fork is user-owned |
| the monorepo itself | maintainer mode | maintainers only |

**Fork mode** needs no write access to the monorepo, so PR authors can migrate their own
PRs and keep working on them. The PR is opened with "Allow edits by maintainers" enabled.
GitHub supports that setting for user-owned forks only, so for a fork owned by an
organisation, maintainers cannot push to the branch.

**Maintainer mode** is for PRs a maintainer wants to finish, for example because the
author has gone quiet. The author cannot push to the resulting branch; see
[After migration](#after-migration) for how they can take over.

### Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — used to run the script with its inline dependencies
- [`git-lfs`](https://git-lfs.com) — to carry over test data stored in LFS
- GitHub auth: either the `gh` CLI (`gh auth login`) or a `GITHUB_TOKEN` environment
  variable holding a classic token with `repo` scope. Fine-grained tokens do not work in
  fork mode: they cannot open PRs or post comments on repositories owned by someone else.
- A clone of your fork of the monorepo (fork mode), or a clone of the monorepo itself
  with write access (maintainer mode). `gh repo fork <monorepo> --clone` creates and
  clones a fork in one step.

### Usage

The script is not part of the monorepo, but uv can run it straight from its URL. Run it
from inside your clone of the monorepo or of your fork:

```sh
SCRIPT=https://github.com/twiggler/dissect-monorepo/raw/master/utils/migrate_pr.py

# Always dry-run first — shows the mode, the files, the commit and the draft PR body, and
# checks that the changes apply. Nothing is pushed or created.
uv run "$SCRIPT" https://github.com/fox-it/dissect.util/pull/42 --dry-run

# Migrate for real
uv run "$SCRIPT" https://github.com/fox-it/dissect.util/pull/42
```

From a clone of this repository, pass the path to the monorepo clone instead:

```sh
uv run utils/migrate_pr.py https://github.com/fox-it/dissect.util/pull/42 \
    --monorepo-path /path/to/clone
```

### What it does

1. Fetches the PR, its commits and its merge base from the GitHub API, and compares
   `origin` with the target to determine the mode.
2. Fetches the merge base and the head of the PR into a throwaway bare repository, and
   rewrites both trees to the monorepo layout:
   - `dissect/...` → `projects/<package>/src/dissect/...`
   - everything else → `projects/<package>/...`; root-level files other than `tests/` are
     flagged for review
   - changes to paths the migration did not carry over or replaced (`tox.ini`, `.github/`,
     `.gitignore`, `.git-blame-ignore-revs`, `tests/_docs/Makefile`, `pyproject.toml`)
     are dropped
3. Applies the diff between the two trees, which is what GitHub shows under "Files
   changed", to the target's `main` in a temporary index, and commits it. Your working
   tree and current branch are not touched.
4. The commit's author is the PR author, as they appear in their own commits. Other
   commit authors become `Co-authored-by:` trailers, and the message lists the original
   commit messages and ends with a `Migrated-from:` trailer.
5. Creates the local branch `migrate/<package>/pr-<N>`, pushes it to `origin` and opens a
   draft PR on the target titled `[migrated] <original title>`.
6. Posts a comment on the original PR with a link to the new draft. This step is skipped
   if the legacy repository is archived, because archived repositories don't accept
   comments.

The PR is always squashed. Replaying its commits one by one fails for PRs that merged the
legacy default branch into their branch, which about a third of the open PRs did. The
legacy repositories squash-merge anyway, so the individual commits would not have
survived the merge.

### After migration

The resulting PR is a **draft**. Review the diff, address any warnings noted in the
PR body, then mark it ready for review. The original PR can be closed once the
migrated one is merged.

To keep working on it, switch to the branch; it tracks `origin`, so `git push` works:

```sh
git switch migrate/dissect.util/pr-42
```

In maintainer mode the branch lives in the monorepo, so the PR author cannot push to it.
To continue the work, the author fetches the branch into a clone of their own fork and
opens a PR from there; a maintainer then closes the draft:

```sh
git fetch https://github.com/<owner>/<monorepo>.git migrate/dissect.util/pr-42
git switch -c <your-branch> FETCH_HEAD
git push origin <your-branch>
```

### Git LFS files

Only the LFS files the PR adds or changes are downloaded, straight into the LFS store of
your clone, and uploaded to the LFS store of `origin` (in fork mode, the fork).

### When the changes do not apply

The diff is applied without a 3-way merge, so it only applies if the files it touches
are the same in the monorepo as at the PR's merge base. If not, the script stops before
creating anything and saves the patch in your temp directory. The usual cause is a PR
based on an old commit: merge the latest default branch of the legacy repository into
the PR (GitHub's "Update branch" button) and run the script again.
