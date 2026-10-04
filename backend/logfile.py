"""A log file in the user's data folder.

The packaged app has no console, so without a file every logged traceback (the
500 handler, a source that failed) would go nowhere and a bug report would have
nothing to read. Only warnings and errors are kept: that leaves out the request
lines, which are noise and name what the user searched for. Every line passes
through `source_http.redact` first, which hides api_key/key/token values (the
private launch link carries `token=`), so a secret cannot reach the file.
"""

import logging
from logging.handlers import RotatingFileHandler

from source_http import redact

LOG_NAME = "lit-review.log"
_MARK = "_lit_review_log_file"


class _RedactingFormatter(logging.Formatter):
    """Formats as usual, then hides secrets in the whole result (message and
    traceback). Done here, not by changing the record, because the same record goes
    on to other handlers."""

    def format(self, record):
        return redact(super().format(record))


def setup(log_dir):
    """Send warnings and errors from every logger to `log_dir/lit-review.log`
    (1 MB, three files kept). Safe to call twice. Returns the log file's path, or
    None if the folder cannot be written (logging is a convenience: the app runs
    without it)."""
    root = logging.getLogger()
    path = log_dir / LOG_NAME
    for handler in root.handlers:
        if getattr(handler, _MARK, False) and handler.baseFilename == str(path):
            return path
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        return None
    setattr(handler, _MARK, True)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(_RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.WARNING:
        root.setLevel(logging.WARNING)
    return path


def teardown():
    """Close and detach the log file (so a test or a restart can remove the folder)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
            handler.close()
