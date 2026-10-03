"""Only one copy of the app may run per user.

Checking whether the port is taken is not enough: two copies started close
together both see a free port before either has bound it, and on Windows
Werkzeug's default socket options then let both bind it without any error. So
each copy first takes a lock on a file; the operating system gives it to exactly
one, and releases it when that process ends for any reason (a crash or a kill
included, so there is never a stale lock to clean up). filelock does this the
same way on Windows, macOS and Linux.
"""

from pathlib import Path

from filelock import FileLock, Timeout


class AlreadyRunning(Exception):
    """Another copy of the app holds the lock: it is running, or still starting."""


def acquire(path):
    """Take the lock at `path` without waiting and return it. The caller must keep
    the returned object alive for as long as the app runs: the lock is released
    when it is released, closed or garbage collected, and by the OS when the
    process exits. Raises AlreadyRunning if another process holds it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path))
    try:
        lock.acquire(blocking=False)
    except Timeout as exc:
        raise AlreadyRunning(f"another copy holds {path}") from exc
    return lock
