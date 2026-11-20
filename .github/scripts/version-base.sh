#!/usr/bin/env bash
# Prints the version the next release is numbered from: the highest X.Y.Z that is already
# used, either by a published release (previous-release.sh) or by any vX.Y.Z tag at all.
# Prints nothing if there is neither. Used by ci.yml (a build on main is this + 1 patch) and
# release.yml (patch, minor or major from this).
#
# Tags count because a tag outlives its release: when a bad release is deleted on GitHub,
# its tag stays (the "Protect version tags" ruleset stops it being deleted or moved), and
# copies that installed it run that version. Numbering from the published releases alone
# would then build and try to publish the same number again: the tag already exists, so
# Publish release would stop, and the fix would never be offered to anyone already on the
# bad version. Skipping a number (a stray tag, or a pulled release) is harmless.
#
# What the build is TESTED against (the upgrade test, the update rehearsal, the dependency
# notes) stays the newest published release, which has downloads: previous-release.sh.
# Needs GH_TOKEN and a checkout with full history.
set -euo pipefail
here="$(dirname "$0")"
published="$(bash "$here/previous-release.sh")"
git fetch -q --tags origin
{
  [ -n "$published" ] && echo "$published"
  git tag --list 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' || true
} | sed 's/^v//' | sort -V | tail -1
