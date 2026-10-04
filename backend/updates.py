"""Is there a newer release of Lit Review on GitHub?

The packaged app is updated by downloading a new zip, so all this does is tell the
user one exists (the page shows a banner with a link). Nothing is downloaded or
replaced. It asks GitHub's public API for the latest release of this project's
repository, with no key and nothing about the user in the request beyond the
program name and version. The answer is kept for a day (a failure for ten
minutes), and the Settings page can switch the check off, in which case the page
never calls it.

A draft or pre-release is never "latest" to that API, so a release the maintainer
has not published yet is not offered.
"""

import re
import threading
import time
from urllib.parse import urlparse

import source_http
import version

REPO = "colinpetree/lit-review"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE_SECONDS = 24 * 60 * 60
FAILURE_CACHE_SECONDS = 10 * 60
MAX_NOTES_CHARS = 2000

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_lock = threading.Lock()
_cached = None  # (expires_at, result)


def parse_version(text):
    """(1, 2, 3) for "v1.2.3" or "1.2.3", else None (a dev build, a typo, a pre-release)."""
    match = _VERSION.match(str(text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def _release_page(url):
    """The release's page if it really is on this project's GitHub page, else None.
    The link is shown to the user and opened in their browser, so it is never taken
    on trust from the reply."""
    url = source_http.safe_url(url)
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path.startswith(f"/{REPO}/"):
        return url
    return None


def _nothing_new(current):
    return {"current": current, "latest": None, "newer": False, "url": None, "notes": ""}


def _fetch(current):
    try:
        response = source_http.get(
            "GitHub",
            LATEST_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"lit-review/{current}"},
        )
        if response.status_code != 200:
            return _nothing_new(current), False
        data = response.json()
    except (source_http.SourceError, ValueError):
        return _nothing_new(current), False
    if not isinstance(data, dict):
        return _nothing_new(current), False

    latest, mine = parse_version(data.get("tag_name")), parse_version(current)
    result = _nothing_new(current)
    if latest is None:
        return result, True
    result["latest"] = ".".join(str(part) for part in latest)
    result["url"] = _release_page(data.get("html_url"))
    notes = data.get("body")
    result["notes"] = notes[:MAX_NOTES_CHARS] if isinstance(notes, str) else ""
    # A dev build (mine is None) never says there is something newer.
    result["newer"] = bool(mine and latest > mine and result["url"])
    return result, True


def check(current=None):
    """{current, latest, newer, url, notes}. Never raises: any trouble is "nothing new"."""
    global _cached
    current = current or version.__version__
    now = time.monotonic()
    with _lock:
        if _cached and _cached[0] > now and _cached[1]["current"] == current:
            return _cached[1]
    result, answered = _fetch(current)
    with _lock:
        _cached = (now + (CACHE_SECONDS if answered else FAILURE_CACHE_SECONDS), result)
    return result


def forget():
    """Drop the kept answer (tests)."""
    global _cached
    with _lock:
        _cached = None
