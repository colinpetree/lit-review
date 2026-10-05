"""The third-party notices the app shows in Settings, License and Notices.

The packaged app carries THIRD_PARTY_NOTICES.txt in its `licenses` folder (the build
puts it there, see pyinstaller.spec), so what the user reads is exactly what shipped.
From source it is the file `packaging/make_notices.py` writes, if that has been run.

Only two fixed places are ever read, never a path taken from a request.
"""

from pathlib import Path

import bundle

FILE_NAME = "THIRD_PARTY_NOTICES.txt"
MAX_BYTES = 2 * 1024 * 1024  # the real file is a few hundred KB; this only stops a runaway one
SOURCE_BUILD_DIR = Path(__file__).resolve().parent.parent / "packaging" / "build"


class NoticesUnavailable(Exception):
    """The notices cannot be shown; `status` is the HTTP status the route answers with."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def find_notices():
    """The notices file, or None if there is none: the packaged copy when the app is
    packaged, else the one a source run's `make_notices.py` wrote."""
    candidates = [bundle.resource_path("licenses", FILE_NAME)]
    if not bundle.is_frozen():
        candidates.append(SOURCE_BUILD_DIR / FILE_NAME)
    return next((path for path in candidates if path.is_file()), None)


def read_notices():
    path = find_notices()
    if path is None:
        raise NoticesUnavailable(
            "The notices file is made when the app is built (python packaging/make_notices.py), "
            "so it is not here in a source run until that has been run.",
            404,
        )
    try:
        if path.stat().st_size > MAX_BYTES:
            raise NoticesUnavailable("The notices file is larger than expected, so it was not opened.", 500)
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise NoticesUnavailable(f"The notices file could not be read ({exc.strerror or 'error'}).", 500) from exc
