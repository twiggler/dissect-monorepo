#!/usr/bin/env bash
set -euo pipefail

# Replace the entire contents of a GitHub repository with a locally built monorepo.
# Usage: ./overwrite_remote.sh [--yes] SOURCE_DIR OWNER/REPO
#   SOURCE_DIR  Local monorepo checkout, e.g. the output of run_pipeline.sh.
#   OWNER/REPO  GitHub repository to overwrite, e.g. twiggler/dissect-monorepo-test.
#   --yes       Skip the confirmation prompt.
#
# Afterwards the remote has exactly one branch ('main', also the default branch)
# and exactly the local tags. All open pull requests are closed.
# Requires git, git-lfs and an authenticated gh CLI.

BRANCH=main

die() { echo "Error: $*" >&2; exit 1; }
list() { if (( $# )); then echo "$*"; else echo "none"; fi; }

ASSUME_YES=false
if [[ "${1:-}" == "--yes" ]]; then ASSUME_YES=true; shift; fi
[[ $# -eq 2 ]] || { echo "Usage: $0 [--yes] SOURCE_DIR OWNER/REPO" >&2; exit 1; }

SOURCE_DIR=$(realpath "$1")
REPO=$2
URL="https://github.com/$REPO.git"

cd "$SOURCE_DIR"
git rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null || die "$SOURCE_DIR has no '$BRANCH' branch"
gh repo view "$REPO" --json name >/dev/null || die "cannot access $REPO"

# LFS objects are uploaded by the git-lfs pre-push hook. Without it the remote
# would receive LFS pointers whose objects are missing.
if [[ -n "$(git lfs ls-files)" ]] && ! grep -qs 'git lfs pre-push' "$(git rev-parse --git-path hooks/pre-push)"; then
  die "Git LFS pre-push hook is not installed in $SOURCE_DIR (run 'git lfs install --local')"
fi

mapfile -t other_branches < <(git ls-remote --heads "$URL" | cut -f2 | grep -vx "refs/heads/$BRANCH")
mapfile -t open_prs < <(gh pr list -R "$REPO" --state open --limit 1000 --json number --jq '.[].number')
# --refs omits the peeled 'refs/tags/X^{}' entries that are listed for annotated tags.
remote_tag_count=$(git ls-remote --refs --tags "$URL" | wc -l)

echo "About to overwrite https://github.com/$REPO with $SOURCE_DIR:"
echo "  force-push '$BRANCH': $(git rev-list --count "$BRANCH") commits"
echo "  replace tags: $remote_tag_count on remote -> $(git tag | wc -l) local"
echo "  close PRs: $(list "${open_prs[@]}")"
echo "  delete branches: $(list "${other_branches[@]#refs/heads/}")"
if ! $ASSUME_YES; then
  read -rp "Type '$REPO' to continue: " answer || true
  [[ "${answer:-}" == "$REPO" ]] || die "aborted, nothing was changed"
fi

echo
echo "=== Pushing '$BRANCH' and tags ==="
# One atomic push; --prune deletes remote tags that do not exist locally.
# All tags MUST go in a single push: GitHub creates no push events when more than
# three tags are pushed at once, so release-native.yml does not fire per tag.
git push --atomic --prune "$URL" "+refs/heads/$BRANCH:refs/heads/$BRANCH" '+refs/tags/*:refs/tags/*'

echo
echo "=== Setting default branch to '$BRANCH' ==="
# Skip when already set: changing it needs admin rights, which the nightly
# refresh credential deliberately lacks.
if [[ "$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name)" == "$BRANCH" ]]; then
  echo "Already '$BRANCH'"
else
  gh repo edit "$REPO" --default-branch "$BRANCH"
fi

echo
echo "=== Closing open PRs ==="
for pr in "${open_prs[@]}"; do
  gh pr close -R "$REPO" "$pr"
done

echo
echo "=== Deleting other branches ==="
# GitHub refuses to delete the default branch, so this must come after switching it.
if (( ${#other_branches[@]} )); then
  git push --atomic "$URL" --delete "${other_branches[@]}"
fi

echo
echo "=== Verifying ==="
diff <(git for-each-ref --format='%(objectname)%09%(refname)' "refs/heads/$BRANCH" refs/tags | sort) \
     <(git ls-remote --refs --heads --tags "$URL" | sort) \
  || die "remote refs differ from local refs (see diff above)"
echo "Done: https://github.com/$REPO matches $SOURCE_DIR"
