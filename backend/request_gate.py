"""Lets a restore replace the database file only while no other request is using it.

Every API request registers on the way in (`enter`) and leaves when it is done (`leave`).
A restore calls `close_when_quiet`: new requests are turned away from that moment, and it
waits (up to a limit) for the ones already running to finish. Without this, a scoring
request in the middle of writing could land its results in the old file as it is being
replaced, or in half of the new one.
"""

import threading


class RequestGate:
    def __init__(self):
        self._cond = threading.Condition()
        self._active = 0
        self._closed = False

    def enter(self):
        """Register a request. False (and not registered) while the gate is closed."""
        with self._cond:
            if self._closed:
                return False
            self._active += 1
            return True

    def leave(self):
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def close_when_quiet(self, timeout, own_requests=1):
        """Turn new requests away and wait until no request but the caller's own (counted in
        `own_requests`) is running. True once it is quiet, with the gate left closed. False
        if the others did not finish within `timeout` seconds, with the gate open again."""
        with self._cond:
            self._closed = True
            if self._cond.wait_for(lambda: self._active <= own_requests, timeout):
                return True
            self._closed = False
            return False

    def open(self):
        with self._cond:
            self._closed = False
            self._cond.notify_all()

    @property
    def closed(self):
        with self._cond:
            return self._closed
