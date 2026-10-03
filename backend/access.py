"""Who may use a running copy of the app, and how a second launch finds it.

The app listens on 127.0.0.1, but that is shared by every account on the
computer (the operating system keeps accounts' files apart, not their network
ports), so another signed-in user could otherwise open your copy: your datasets,
and AI jobs on your API keys. Each copy therefore requires a secret. It is
created once, kept in the user's data folder, and given to the browser in a
private link, which the page keeps in its own storage and sends as an
Authorization header on every API call.

It is deliberately not a cookie: browsers match cookies by host name only, never
by port, so a cookie for this app would also be sent to every other web server
the user's browser visits on 127.0.0.1, which could then use it. Page storage is
kept apart per address and port, and a header is only ever sent by the page's own
script, so neither leaks that way and nothing is sent by another site's request.

The boundary is the user's own profile folder. The secret lives in the data
folder, and the browser keeps its copy in the browser's profile, so both are as
private as the account's files are; keeping a profile private is the machine
owner's job and is not worked around here. (On macOS and Linux the files are
created readable by their owner only, because that is how temporary files are
made there.)

Two small files live next to the lock in the user's data folder:
  access.token   the secret, kept across restarts so stored links keep working
  instance.json  which port the running copy is on and its id, so a second
                 launch by the same user finds that copy (and not someone
                 else's) and opens a browser on it
"""

import json
import os
import secrets
import tempfile
from pathlib import Path

TOKEN_FILE = "access.token"
INSTANCE_FILE = "instance.json"
MIN_TOKEN_LENGTH = 32
_URLSAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _write_atomic(path, text):
    """Write `text` to `path` in one step: the file is written next to it, then moved
    into place, so a crash or a full disk never leaves a half-written file where a
    good one was."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(handle)
    try:
        with open(temp_name, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _valid_token(text):
    return len(text) >= MIN_TOKEN_LENGTH and set(text) <= _URLSAFE


def load_or_create_token(directory):
    """The secret for this user, created on first use and then kept. A file that is
    missing, empty or damaged (including one that is not text at all) is replaced
    with a new secret."""
    path = Path(directory) / TOKEN_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):  # missing, unreadable, or not text at all
        existing = ""
    if _valid_token(existing):
        return existing
    token = secrets.token_urlsafe(32)
    _write_atomic(path, token)
    return token


def launch_url(port, token=None):
    """The address to open in the browser. With a secret it is the private link: the
    secret rides in the fragment (after the #), which a browser never sends to any
    server, so it is not in a request, a log, or a Referer; the page reads it, keeps
    it for that address (browsers keep page storage apart per address and port), and
    removes it from the address bar."""
    if token:
        return f"http://127.0.0.1:{port}/#token={token}"
    return f"http://127.0.0.1:{port}"


def write_instance(directory, port, instance_id):
    _write_atomic(Path(directory) / INSTANCE_FILE, json.dumps({"port": port, "id": instance_id}))


def read_instance(directory):
    """{"port": int, "id": str} for the copy that wrote it, or None if there is no
    usable record. A record can be stale (a copy that crashed); whether the copy
    is really there is decided by asking it, never by this file."""
    try:
        data = json.loads((Path(directory) / INSTANCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    port, instance_id = data.get("port"), data.get("id")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        return None
    if not isinstance(instance_id, str) or not instance_id:
        return None
    return {"port": port, "id": instance_id}


def clear_instance(directory, instance_id):
    """Remove the record, but only if it is still this copy's (a newer copy may
    already have written its own)."""
    current = read_instance(directory)
    if current and current["id"] == instance_id:
        try:
            (Path(directory) / INSTANCE_FILE).unlink()
        except OSError:
            pass
