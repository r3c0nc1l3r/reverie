#!/usr/bin/env bash
# Build the documentation site and push it to the gh-pages branch.
#
# GitHub Pages serves the branch at https://r3c0nc1l3r.github.io/reverie/.
# Usage: scripts/publish-docs.sh [remote]   (default remote: origin)
# Set DRY_RUN=1 to build and commit in a temporary worktree (removed on exit) without pushing.
set -euo pipefail

remote="${1:-origin}"
branch="gh-pages"
root="$(git rev-parse --show-toplevel)"
site="$root/website"
source_rev="$(git -C "$root" rev-parse --short HEAD)"

echo "Building the site from $source_rev"
(cd "$site" && npm ci && npm run build)

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Start from the existing gh-pages branch when there is one, so history is kept.
if git -C "$root" ls-remote --exit-code --heads "$remote" "$branch" >/dev/null 2>&1; then
	git -C "$root" fetch "$remote" "$branch"
	git -C "$root" worktree add --force "$work/out" FETCH_HEAD
	(cd "$work/out" && git checkout -B "$branch")
else
	git -C "$root" worktree add --force --detach "$work/out"
	(cd "$work/out" && git checkout --orphan "$branch")
fi
trap 'git -C "$root" worktree remove --force "$work/out" 2>/dev/null || true; rm -rf "$work"' EXIT

# Replace the branch contents with the fresh build.
(cd "$work/out" && git rm -rfq --ignore-unmatch . && git clean -fdxq)
cp -R "$site/dist/." "$work/out/"
touch "$work/out/.nojekyll"

cd "$work/out"
git add -A
if git diff --cached --quiet; then
	echo "No changes to publish."
	exit 0
fi
git commit -qm "docs: publish site from $source_rev"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
	echo "DRY_RUN=1: built and committed; not pushing."
	git log --oneline -1
	exit 0
fi
git push "$remote" "$branch"
echo "Published to $remote/$branch."
