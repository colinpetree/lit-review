"""Version numbers and the project's GitHub address, shared by the update code.

The check itself lives in updater.py (it fetches the signed manifest, update_manifest.py), and the
packaged app always runs it; the old "ask the GitHub API whether a newer release exists" notice is
gone. This module stays small on purpose, so the manifest code can use `parse_version` without
importing the updater.
"""

import re

REPO = "colinpetree/lit-review"

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text):
    """(1, 2, 3) for "v1.2.3" or "1.2.3", else None (a dev build, a typo, a pre-release)."""
    match = _VERSION.match(str(text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None
