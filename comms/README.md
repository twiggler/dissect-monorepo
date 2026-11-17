# comms/

Announcements about the monorepo migration, and the script that posts them.

- `announcement.md` — the announcement, posted as the main discussion on
  [fox-it/dissect.target#1961](https://github.com/fox-it/dissect.target/discussions/1961).
- `announce_discussions.py` — posts an announcement as GitHub Discussions.

## announce_discussions.py

Posts the announcement as the main discussion on `--main` (default: `fox-it/dissect.target`),
and a locked discussion linking to it on every other repository in `migrate/project-list`,
so that all replies go to one thread. Everything is posted in the "Announcements" category.

```sh
# Always dry-run first — only reads from GitHub and prints what would be done
uv run comms/announce_discussions.py --dry-run

# Post
uv run comms/announce_discussions.py
```

- The discussion title is the `# ` heading on the first line of the announcement; the
  rest of the file is the body of the main discussion.
- Repositories that already have a discussion with that title are left alone, so the
  script is safe to re-run after a partial failure.
- Repositories with Discussions disabled are reported and skipped. Enabling Discussions
  requires admin rights on the repository.
- Requires `uv` and GitHub auth (`gh auth login` or a `GITHUB_TOKEN` environment
  variable) with maintain rights on the repositories: only maintainers can start
  discussions in the "Announcements" category.

## Status

- Posted on 2026-11-09: the main discussion and 29 locked pointers.
- `fox-it/dissect.hypervisor` has no pointer yet. Once an admin enables Discussions
  there, re-run the script; it only adds the missing pointer.

## Follow-ups

- When the dates are decided, update `announcement.md` and edit the main discussion to
  match. The script does not update discussions that already exist.
- Before `fox-it/dissect.target` is archived, post a final comment on the main
  discussion pointing to `fox-it/dissect`: archived repositories are read-only.
