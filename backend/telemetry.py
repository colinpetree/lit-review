"""Anonymous usage counts, so the developer can tell how many copies are in use.

Two signals go to one counting service, each carrying only `{event, version, platform}`:
- `daily`: at most once per UTC day, while the packaged app is running.
- `new_install`: once, for a copy started with no data folder yet (`note_launch`).
There is no install ID, no IP kept by the service and no setting, on purpose (see the License and
Notices page). What is remembered here is one small file, `census.json`: the date of the last
`daily` that was accepted and a flag for a `new_install` still to send. Nothing in this module may
ever show an error to the user or hold up an update check: every failure is logged and ignored.
"""

import json
import logging
import os
import threading
import time
from urllib.parse import urlparse

import requests

import db
import source_http
import update_manifest as um
import version

log = logging.getLogger(__name__)

# The counting service (telemetry-worker/). Empty means nothing is ever sent. Every shipped copy
# carries this name, so the hostname has to keep working (or answer 410 to make copies stop).
ENDPOINT = "https://litreview-data.colinpetree.com/"
TIMEOUT_SECONDS = 5
FILE_NAME = "census.json"


def _path():
    return db.DB_PATH.parent / FILE_NAME


def _load():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(state):
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("Could not save the usage count state (%s).", exc)


_new_this_run = False  # a new install whose record could not be written still gets counted this run


def note_launch():
    """Call once at start-up, after the instance lock and BEFORE the database is created.
    The first time this runs in a data folder it records whether the folder is new (no database
    yet): only then is a `new_install` owed. A folder that already holds a database (someone who
    updated to a version with counting, or reinstalled over their data) is never counted as new."""
    global _new_this_run
    if _path().exists():
        return
    fresh = not db.DB_PATH.exists()
    _new_this_run = fresh
    _save({"pending_new_install": fresh})


def _endpoint():
    """The URL to send to, or None. With LIT_REVIEW_TESTING=1 nothing ever goes to the real
    service (a launched test copy, or a hand-run check against a fake release server, would
    otherwise add fake installs to the real numbers): only LIT_REVIEW_CENSUS_URL, and only if it
    is on this computer."""
    if um.testing_enabled():
        override = os.environ.get("LIT_REVIEW_CENSUS_URL")
        if override and urlparse(override).hostname in ("127.0.0.1", "localhost", "::1"):
            return override
        return None
    return ENDPOINT or None


def _post(url, body):
    """The HTTP status of one send, or None if it could not be made."""
    try:
        response = requests.post(
            url, json=body, headers={"User-Agent": source_http.USER_AGENT},
            timeout=TIMEOUT_SECONDS, allow_redirects=False,
        )
    except requests.RequestException as exc:
        log.warning("Usage count not sent (%s): %s", type(exc).__name__, source_http.redact(exc))
        return None
    status = response.status_code
    response.close()
    return status


def send_if_due(today=None, post=None):
    """Send whatever is owed. Returns the list of events accepted, for tests."""
    global _new_this_run, _failed
    _failed = False
    url = _endpoint()
    if not url:
        return []
    running = version.__version__
    if running.endswith("-dev") and not um.testing_enabled():
        return []  # a build made by hand is the maintainer's, not a user's
    state = _load()
    if state.get("disabled"):
        return []
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    owed = []
    if state.get("pending_new_install") or _new_this_run:
        owed.append("new_install")
    if state.get("last_daily") != today:
        owed.append("daily")
    post = post or _post
    platform_key = um.platform_key() or "other"
    sent = []
    for event in owed:
        status = post(url, {"event": event, "version": running, "platform": platform_key})
        if status == 410:  # the service asks old copies to stop
            state["disabled"] = True
            _save(state)
            return sent
        if status is None or not 200 <= status < 300:
            if status is not None:
                log.warning("Usage count not accepted (status %s).", status)
            _failed = True  # the thread waits longer before the next try
            return sent
        if event == "new_install":
            _new_this_run = False
            state["pending_new_install"] = False
        else:
            state["last_daily"] = today
        _save(state)
        sent.append(event)
    return sent


# ------------------------------------------------------------------ the thread

FIRST_SEND_SECONDS = 20  # after the update check's first pass, so start-up is not crowded
RECHECK_SECONDS = 60 * 60  # an hour: cheap (nothing is sent unless a new UTC day began or a send is owed)
# After a failed send the wait grows, so a service that is down, full or refusing this version
# is asked a few times a day at most, not every hour by every copy.
BACKOFF_SECONDS = (60 * 60, 3 * 60 * 60, 6 * 60 * 60, 12 * 60 * 60)
_failed = False  # the last send_if_due ended on a failed send
_thread = None
_stop = threading.Event()


def start_background():
    """Start the sending thread (once). It is its own thread, apart from the update check, so a
    slow or failing counting service can never delay an update, and a copy left running for
    days still reports each day however the update check's own timing drifts."""
    global _thread
    if _thread and _thread.is_alive():
        return _thread
    _stop.clear()

    def loop():
        delay, failures = FIRST_SEND_SECONDS, 0
        while not _stop.wait(delay):
            try:
                send_if_due()
            except Exception:  # noqa: BLE001 - counting must never take the app down
                log.exception("The usage count crashed.")
            if _failed:
                delay = BACKOFF_SECONDS[min(failures, len(BACKOFF_SECONDS) - 1)]
                failures += 1
            else:
                delay, failures = RECHECK_SECONDS, 0

    _thread = threading.Thread(target=loop, name="usage-count", daemon=True)
    _thread.start()
    return _thread


def stop_background():
    _stop.set()
