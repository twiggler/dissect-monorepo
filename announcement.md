# Dissect is moving to a monorepo

**TL;DR:** We're merging the `dissect.*` repositories into one repository: `<MONOREPO_URL>`. If you install Dissect from PyPI, nothing changes for you. If you contribute, your workflow will change, and we'd like your feedback before **<FEEDBACK_DEADLINE>**.

## Why

The `dissect.*` packages depend heavily on each other, but they live in 31 separate repositories. A monorepo gives us:

- **One PR for a change that spans packages.** Today that takes a set of linked PRs, which have to be merged in the right order.
- **Earlier failure detection.** A change to a core package such as `dissect.cstruct` automatically runs the tests of every package that depends on it, before anything is released.
- **One set of tooling and config.** Lint rules and CI are defined once, so they can't drift apart between repositories.
- **Faster everything.** uv sets up environments much faster than pip, locally and in CI, and CI only tests the packages affected by a change.

## What changes

- **Layout:** each package lives in `projects/<package>/` with a `src/` layout, for example `projects/dissect.target/src/dissect/target/`.
- **[uv](https://docs.astral.sh/uv/)** replaces pip and tox for managing environments and dependencies, and it's fast. Resolving, installing and creating environments are roughly ten times faster than with pip. Packages are cached and shared between environments, so recreating an environment or testing against another Python version takes seconds rather than a full reinstall. One `uv sync` sets up all 31 packages, with a single `uv.lock` for the whole workspace, and `dissect.*` dependencies resolve to your local checkout.
- **[just](https://just.systems/)** runs the everyday tasks: `just test dissect.target`, `just test-affected`, `just lint`. Run `just --list` to see all of them.
- **Versions and tags:** each package's version is now a fixed field in its `pyproject.toml`. It is no longer derived from a git tag. Tags now include the package name, for example `dissect.util/3.24.1`. If you build packages from our GitHub tags (for a Linux distribution, say), please let us know.
- **History is kept:** all commits and tags from the old repositories are in the monorepo.

**What stays the same:** package names on PyPI, import paths, version numbers, and `pip install dissect`. Further, `acquire`, `flow.record` and `dissect-docs` stay in their own repositories.

## Open pull requests

- After **<PR_CUTOFF>**, please don't open new PRs on the old repositories.
- After go-live on **<GO_LIVE>**, you can move your PR to the monorepo yourself with [`migrate_pr.py`](https://github.com/twiggler/dissect-monorepo/blob/master/utils/README.md). The tool rewrites the file paths to the new layout and keeps the authors, commit messages and PR description. The new PR is opened from your fork, so you can keep pushing to it. You need `uv`, `git-filter-repo` and a logged-in `gh`:

  ```sh
  gh repo fork <MONOREPO_URL> --clone   # creates and clones your fork
  cd <clone-directory>
  uv run https://github.com/twiggler/dissect-monorepo/raw/master/utils/migrate_pr.py <old-pr-url> --dry-run
  uv run https://github.com/twiggler/dissect-monorepo/raw/master/utils/migrate_pr.py <old-pr-url>
  ```

  The first command shows what will happen; the second opens the PR. If the patches don't apply, rebase your old PR on the latest `main` of its repository and try again.
- Before **<ARCHIVE>**, we'll close PRs that are still open, with a comment explaining how to migrate them. You can still migrate your PR after that, also once the old repository is archived.

## Timeline

| Date | Step |
|---|---|
| Now – <FEEDBACK_DEADLINE> | Feedback. Try out the test instance (see below) |
| <PR_CUTOFF> | PR cut-off: no new PRs on the old repositories |
| <FREEZE> | Freeze: last merges on the old repositories |
| <GO_LIVE> | Go-live: we build the monorepo from the final state of the old repositories. From now on you can migrate your open PRs |
| <ARCHIVE> | We close the remaining PRs, move open issues to the monorepo, and archive the old repositories. They stay readable, issues and PRs included |

## Try it out

- **Test instance of the monorepo:** https://github.com/twiggler/dissect-monorepo-test. Clone it and try your usual workflow: `uv sync`, `just test <package>`, `just --list`.
- **Migration scripts and design docs:** https://github.com/twiggler/dissect-monorepo. The reasoning behind the tooling, testing and release choices is in [`template/.monorepo/doc/`](https://github.com/twiggler/dissect-monorepo/tree/master/template/.monorepo/doc).

## Feedback

 We want your input on the details: the tooling, the layout, the contributor workflow, the timeline, and anything this breaks for you. Please reply in this thread.
