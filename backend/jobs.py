"""Background jobs: slow work the app finishes by itself, whatever page the user is on.

Starting a dataset search, an evaluation, a check for new papers or an abstract lookup only adds a row
to the `job` table (db.enqueue_job). Two worker threads take rows from it:

  * the paid lane runs dataset searches, checks for new papers and evaluations, one at a time in the
    order they were queued (they spend AI money or search quota, and run side by side they would trip
    each other's rate limits);
  * the lookup lane runs abstract lookups, which cost nothing, so they never wait behind a long
    evaluation.

What a job does lives in app.py (it is the code the routes already used); it is registered here with
`register`. A handler gets a `JobContext` and works in small units (one chunk of papers, one search),
each inside `ctx.unit()`:

  * `ctx.check()` raises `JobStopped` when the user stopped the job (or the app is closing), so a stop
    takes effect between units. A unit already running finishes, and what it cost is still billed.
  * `ctx.unit()` takes a place in the request gate, so a restore or an update install waits for the
    unit in progress, and the unit cannot start while one is under way.
  * If a restore replaced the database meanwhile (`db.epoch()` changed), the job's ids mean nothing
    in the new data: it ends without writing anything (`JobAbandoned`).

Nothing starts at import: `start()` is called from main(), so tests stay in control (they call
`drain()` to run what is queued on their own thread).
"""

import logging
import threading
import time
from contextlib import contextmanager

import db
from source_http import redact

log = logging.getLogger(__name__)

PAID_KINDS = ("dataset_search", "dataset_refresh", "run_score")
LOOKUP_KINDS = ("find_abstracts",)
ALL_KINDS = PAID_KINDS + LOOKUP_KINDS

# How long a lane sleeps when nothing is queued before looking again (it is woken at once by wake()).
IDLE_SECONDS = 5
# How long a unit waits for the request gate to reopen (a restore or update is under way).
GATE_POLL_SECONDS = 0.5
# Waits before asking the AI again after a failure that may pass (rate limit, overload, dropped
# connection). Tests set it to zeros.
RETRY_WAITS = (5, 20, 60)


class JobStopped(Exception):
    """The job should end now, incomplete. The message is shown to the user."""


class JobFailed(Exception):
    """The job cannot go on; it ends incomplete with this message (safe to show)."""


class JobAbandoned(Exception):
    """The database was replaced while the job ran: end without writing anything."""


HANDLERS = {}
_gate = None
_stop_all = threading.Event()
_wake = threading.Condition()
_threads = []


def register(kind, handler):
    HANDLERS[kind] = handler


def configure(gate):
    """The request gate units run inside (see request_gate.py)."""
    global _gate
    _gate = gate


def wake():
    with _wake:
        _wake.notify_all()


class JobContext:
    def __init__(self, job):
        self.job = job
        self.id = job["id"]
        self.params = dict(job["params"])
        self.progress = dict(job["progress"])
        self._epoch = db.epoch()

    def check(self):
        """Raise if the job should not carry on."""
        if db.epoch() != self._epoch:
            raise JobAbandoned()
        if _stop_all.is_set():
            raise JobStopped("Lit Review was closed before this finished. Resume it to carry on.")
        if db.stop_requested(self.id):
            raise JobStopped(db.STOPPED_BY_USER)

    def set_progress(self, **fields):
        """Merge fields into the job's saved progress (shown on the pages)."""
        self.progress.update(fields)
        db.update_job(self.id, progress=self.progress)

    def save_params(self, **fields):
        """Keep something a resume should not have to work out (or pay for) again."""
        self.params.update(fields)
        db.update_job(self.id, params=self.params)

    def sleep(self, seconds):
        """Wait, but notice a stop within a quarter of a second."""
        end = time.monotonic() + seconds
        while True:
            self.check()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.25, left))

    @contextmanager
    def unit(self):
        """One piece of work (a chunk of papers, a search), inside the request gate."""
        while True:
            self.check()
            if _gate is None or _gate.enter():
                break
            time.sleep(GATE_POLL_SECONDS)
        try:
            # A restore that finished while this waited for the gate has replaced the data.
            self.check()
            yield
        finally:
            if _gate is not None:
                _gate.leave()


def _run(job):
    handler = HANDLERS.get(job["kind"])
    ctx = JobContext(job)
    status, error = "completed", None
    try:
        if handler is None:
            raise JobFailed("This kind of job is not supported by this version.")
        handler(ctx)
    except JobAbandoned:
        return
    except (JobStopped, JobFailed) as exc:
        status, error = "incomplete", str(exc) or "Stopped."
    except Exception as exc:  # noqa: BLE001 - one job's bug must not stop the lane
        log.error("Job %s (%s) failed:", job["id"], job["kind"], exc_info=True)
        status, error = "incomplete", f"Something went wrong ({redact(exc)}). Resume it to try again."
    if db.epoch() != ctx._epoch:
        return
    try:
        db.finish_job(job["id"], status, redact(error) if error else None)
    except Exception:  # noqa: BLE001
        log.error("Could not record how job %s ended:", job["id"], exc_info=True)


def drain(limit=100):
    """Run queued jobs on this thread until none are left (jobs they queue included). For tests."""
    ran = 0
    while ran < limit:
        job = db.claim_next_job(ALL_KINDS)
        if job is None:
            return ran
        _run(job)
        ran += 1
    return ran


def _lane(kinds):
    while not _stop_all.is_set():
        try:
            job = db.claim_next_job(kinds)
        except Exception:  # noqa: BLE001 - the database may be mid-restore; look again shortly
            log.error("Could not look for queued jobs:", exc_info=True)
            job = None
        if job is None:
            with _wake:
                _wake.wait(IDLE_SECONDS)
            continue
        _run(job)


def start():
    """Start the two lanes (once)."""
    if _threads:
        return
    _stop_all.clear()
    for name, kinds in (("jobs-paid", PAID_KINDS), ("jobs-lookup", LOOKUP_KINDS)):
        thread = threading.Thread(target=_lane, args=(kinds,), name=name, daemon=True)
        thread.start()
        _threads.append(thread)


def stop(timeout=5):
    """Ask running jobs to wind down (they end incomplete at their next unit) and wait briefly."""
    _stop_all.set()
    wake()
    deadline = time.monotonic() + timeout
    for thread in _threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    _threads.clear()


def running():
    return any(t.is_alive() for t in _threads)


# What the pages show -------------------------------------------------------------------------------
# One word per item: "queued", "running", "stopping" (asked to stop, finishing its batch),
# "incomplete" or "completed". Worked out here, once, so every page agrees.

def public_job(job):
    """The job as the pages see it (without the private parameters it was started with)."""
    if job is None:
        return None
    return {
        key: job[key]
        for key in (
            "id", "kind", "status", "dataset_id", "run_id", "progress", "error",
            "stop_requested", "created_at", "started_at", "finished_at",
        )
    }


def job_state(job):
    if job["status"] == "running":
        return "stopping" if job["stop_requested"] else "running"
    return job["status"]


def _active(job):
    return job["status"] in ("queued", "running")


def dataset_state(pending, jobs):
    """(state, job) for a dataset card, given the jobs on that dataset. A dataset whose search has
    not finished shows how that search is going. A finished one shows Running while a check for new
    papers or a lookup is under way, and otherwise Completed: a failed check or lookup is reported on
    the dataset's page and does not make a good dataset look unfinished."""
    searches = [j for j in jobs if j["kind"] == "dataset_search"]
    if pending:
        if not searches:
            return "incomplete", None
        search = max(searches, key=lambda j: j["id"])
        state = job_state(search)
        return ("incomplete" if state == "completed" else state), search
    active = [j for j in jobs if _active(j)]
    if active:
        # A running one before one that is only waiting.
        job = sorted(active, key=lambda j: (j["status"] != "running", j["id"]))[0]
        return job_state(job), job
    return "completed", None


def run_state(unscored, jobs):
    """(state, job) for an evaluation. Papers still ungraded and nothing working on them is
    Incomplete, whether or not a job ever ran (this is the rule the lists always used)."""
    scores = [j for j in jobs if j["kind"] == "run_score"]
    active = [j for j in scores if _active(j)]
    if active:
        job = sorted(active, key=lambda j: (j["status"] != "running", j["id"]))[0]
        return job_state(job), job
    if unscored:
        latest = max(scores, key=lambda j: j["id"]) if scores else None
        return "incomplete", latest if latest and latest["status"] == "incomplete" else None
    return "completed", None
