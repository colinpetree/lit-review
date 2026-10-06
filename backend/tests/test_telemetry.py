import json

import pytest

import db
import telemetry
import version


@pytest.fixture(autouse=True)
def counting_on(monkeypatch):
    monkeypatch.setattr(telemetry, "ENDPOINT", "https://counts.example/ping")
    monkeypatch.setattr(version, "__version__", "1.2.3")
    monkeypatch.setattr(telemetry, "_new_this_run", False)
    monkeypatch.setattr(telemetry, "_failed", False)
    monkeypatch.delenv("LIT_REVIEW_TESTING", raising=False)
    monkeypatch.delenv("LIT_REVIEW_CENSUS_URL", raising=False)


class Sender:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, url, body):
        self.calls.append((url, body))
        return self.statuses.pop(0) if self.statuses else 200


def census():
    return json.loads((db.DB_PATH.parent / telemetry.FILE_NAME).read_text())


def test_new_data_folder_owes_a_new_install():
    telemetry.note_launch()
    assert census() == {"pending_new_install": True}


def test_existing_database_is_not_a_new_install():
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.DB_PATH.write_bytes(b"")
    telemetry.note_launch()
    assert census() == {"pending_new_install": False}


def test_note_launch_decides_only_once():
    telemetry.note_launch()
    db.DB_PATH.write_bytes(b"")  # the first launch created the database
    telemetry.note_launch()
    assert census()["pending_new_install"] is True


def test_sends_only_three_fields_and_new_install_once():
    telemetry.note_launch()
    send = Sender()
    assert telemetry.send_if_due(today="2026-10-06", post=send) == ["new_install", "daily"]
    for _url, body in send.calls:
        assert set(body) == {"event", "version", "platform"}
        assert body["version"] == "1.2.3"
    assert telemetry.send_if_due(today="2026-10-06", post=send) == []
    assert telemetry.send_if_due(today="2026-10-07", post=send) == ["daily"]
    assert [c[1]["event"] for c in send.calls] == ["new_install", "daily", "daily"]


def test_failure_is_retried_and_loses_nothing():
    telemetry.note_launch()
    assert telemetry.send_if_due(today="2026-10-06", post=Sender(None)) == []
    assert telemetry.send_if_due(today="2026-10-06", post=Sender(500)) == []
    assert census()["pending_new_install"] is True
    assert telemetry.send_if_due(today="2026-10-06", post=Sender()) == ["new_install", "daily"]


def test_daily_failure_after_new_install_keeps_daily_owed():
    telemetry.note_launch()
    assert telemetry.send_if_due(today="2026-10-06", post=Sender(200, 503)) == ["new_install"]
    state = census()
    assert state["pending_new_install"] is False and "last_daily" not in state


def test_gone_reply_stops_sending_for_good():
    telemetry.note_launch()
    send = Sender(410)
    assert telemetry.send_if_due(today="2026-10-06", post=send) == []
    assert telemetry.send_if_due(today="2026-10-08", post=send) == []
    assert len(send.calls) == 1


def test_nothing_sent_without_an_endpoint(monkeypatch):
    monkeypatch.setattr(telemetry, "ENDPOINT", "")
    send = Sender()
    assert telemetry.send_if_due(post=send) == []
    assert send.calls == []


def test_dev_version_never_sends(monkeypatch):
    monkeypatch.setattr(version, "__version__", "0.0.0-dev")
    send = Sender()
    assert telemetry.send_if_due(post=send) == []
    assert send.calls == []


def test_override_needs_testing_flag_and_loopback(monkeypatch):
    monkeypatch.setattr(telemetry, "ENDPOINT", "")
    monkeypatch.setenv("LIT_REVIEW_CENSUS_URL", "http://127.0.0.1:9/ping")
    monkeypatch.delenv("LIT_REVIEW_TESTING", raising=False)
    assert telemetry._endpoint() is None
    monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
    assert telemetry._endpoint() == "http://127.0.0.1:9/ping"
    monkeypatch.setenv("LIT_REVIEW_CENSUS_URL", "https://evil.example/ping")
    assert telemetry._endpoint() is None


def test_unreachable_service_is_quiet(monkeypatch):
    monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
    monkeypatch.setenv("LIT_REVIEW_CENSUS_URL", "http://127.0.0.1:1/ping")  # nothing listens
    telemetry.note_launch()
    assert telemetry.send_if_due(today="2026-10-06") == []


def test_a_new_install_is_still_counted_when_its_record_cannot_be_written(monkeypatch):
    monkeypatch.setattr(telemetry, "_save", lambda state: None)  # the disk refused the file
    telemetry.note_launch()
    send = Sender()
    assert telemetry.send_if_due(today="2026-10-06", post=send) == ["new_install", "daily"]
    telemetry.send_if_due(today="2026-10-06", post=send)  # nothing was saved, so only the day repeats
    assert [call[1]["event"] for call in send.calls] == ["new_install", "daily", "daily"]


class _Service:
    """A real HTTP server on this computer that records what a send puts on the wire."""

    def __init__(self, status=204):
        import http.server
        import threading

        self.bodies, self.methods = [], []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.bodies.append(json.loads(self.rfile.read(length)))
                outer.methods.append(self.command)
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_a_real_send_puts_exactly_three_fields_on_the_wire(monkeypatch):
    service = _Service()
    try:
        monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
        monkeypatch.setenv("LIT_REVIEW_CENSUS_URL", service.url)
        telemetry.note_launch()
        assert telemetry.send_if_due(today="2026-10-06") == ["new_install", "daily"]
    finally:
        service.close()
    assert service.methods == ["POST", "POST"]
    assert [b["event"] for b in service.bodies] == ["new_install", "daily"]
    for body in service.bodies:
        assert set(body) == {"event", "version", "platform"}
        assert body["version"] == "1.2.3" and body["platform"]


def test_a_redirect_is_not_followed_or_counted(monkeypatch):
    service = _Service(status=302)
    try:
        monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
        monkeypatch.setenv("LIT_REVIEW_CENSUS_URL", service.url)
        assert telemetry.send_if_due(today="2026-10-06") == []
    finally:
        service.close()
    assert len(service.bodies) == 1  # asked once, not chased


def test_the_thread_sends_and_survives_a_crash(monkeypatch):
    import threading

    calls, done = [], threading.Event()

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        done.set()

    monkeypatch.setattr(telemetry, "send_if_due", flaky)
    monkeypatch.setattr(telemetry, "FIRST_SEND_SECONDS", 0)
    monkeypatch.setattr(telemetry, "RECHECK_SECONDS", 0.01)
    monkeypatch.setattr(telemetry, "_thread", None)
    try:
        thread = telemetry.start_background()
        assert telemetry.start_background() is thread  # started once
        assert done.wait(5)  # the crash did not end the loop
    finally:
        telemetry.stop_background()
    thread.join(5)
    assert not thread.is_alive()


def test_testing_mode_never_reaches_the_real_service(monkeypatch):
    # ENDPOINT is the real address here. A launched test copy, or a hand-run check against a fake
    # release server, sets only LIT_REVIEW_TESTING: it must not add fake installs to the real numbers.
    monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
    assert telemetry._endpoint() is None
    send = Sender()
    telemetry.note_launch()
    assert telemetry.send_if_due(today="2026-10-06", post=send) == []
    assert send.calls == []


def test_the_census_url_alone_cannot_make_a_dev_build_send(monkeypatch):
    monkeypatch.setattr(version, "__version__", "0.0.0-dev")
    monkeypatch.setenv("LIT_REVIEW_CENSUS_URL", "http://127.0.0.1:9/ping")
    send = Sender()
    assert telemetry.send_if_due(post=send) == []
    assert send.calls == []


def test_a_failed_send_is_flagged_and_a_good_one_clears_it():
    telemetry.note_launch()
    telemetry.send_if_due(today="2026-10-06", post=Sender(503))
    assert telemetry._failed is True
    telemetry.send_if_due(today="2026-10-06", post=Sender())
    assert telemetry._failed is False


def test_the_thread_waits_longer_after_each_failure_and_resets_on_success(monkeypatch):
    waits, results = [], iter([True, True, True, True, True, False])

    class Stop:
        def wait(self, delay):
            waits.append(delay)
            return len(waits) > 7

        def clear(self):
            pass

        def set(self):
            pass

    def fake_send():
        telemetry._failed = next(results, False)

    monkeypatch.setattr(telemetry, "send_if_due", fake_send)
    monkeypatch.setattr(telemetry, "_stop", Stop())
    monkeypatch.setattr(telemetry, "_thread", None)
    thread = telemetry.start_background()
    thread.join(5)
    hour, h3, h6, h12 = telemetry.BACKOFF_SECONDS
    assert waits[:7] == [telemetry.FIRST_SEND_SECONDS, hour, h3, h6, h12, h12, telemetry.RECHECK_SECONDS]
