#!/usr/bin/env bash
# Prints the newest PUBLISHED (not draft, not pre-release) vX.Y.Z release whose commit is
# on main, or nothing if there is none. Used by ci.yml and release.yml, so both agree on
# which release is "previous". It reads releases, not tags, so a tag pushed by hand (or one
# left behind by an abandoned release) can never become the version base. Needs GH_TOKEN
# and a checkout with full history.
set -euo pipefail
git fetch -q --tags origin main
gh release list --repo "$GITHUB_REPOSITORY" --limit 200 --exclude-drafts --exclude-pre-releases --json tagName -q '.[].tagName' \
  | { grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' || true; } \
  | while read -r tag; do
      if git rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null \
        && git merge-base --is-ancestor "refs/tags/$tag^{commit}" origin/main; then
        echo "$tag"
      fi
    done \
  | sort -V | tail -1
