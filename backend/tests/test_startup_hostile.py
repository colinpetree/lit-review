"""check_port against programs that behave badly: redirects, slow or endless
answers, floods, and proxy settings. The probe must talk only to the one
address it was given, finish within a fixed time, and read a bounded amount."""

import socket
import threading
import time

import pytest

import app as app_module
from test_startup import TestCheckPort

GENUINE = TestCheckPort.http_reply('{"app": "lit-review"}')


class Hostile:
    """A throwaway program on a loopback port, with `handler(self, conn, request)`
    run for each connection (request = the bytes it sent first, b"" if none).
    Records how many connections it accepted and every request it saw."""

    def __init__(self, handler):
        self.handler = handler
        self.connections = 0
        self.requests = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        self.listener.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except OSError:
                continue
            self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(1)
            try:
                request = conn.recv(8192)
            except OSError:
                request = b""
            self.requests.append(request)
            self.handler(self, conn, request)
        except OSError:
            pass
        finally:
            conn.close()

    def sleep(self, seconds):
        """Wait, but wake as soon as the test is over."""
        self._stop.wait(seconds)

    @property
    def stopped(self):
        return self._stop.is_set()

    def close(self):
        self._stop.set()
        self._thread.join(5)
        self.listener.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def quick(monkeypatch):
    """A short overall deadline, so the tests of it do not each wait seconds."""
    monkeypatch.setattr(app_module, "HEALTH_PROBE_SECONDS", 1)
    return 1


class TestRedirects:
    def test_a_redirect_is_not_followed_and_nothing_is_requested_from_its_target(self):
        with Hostile(lambda self, conn, req: conn.sendall(GENUINE)) as target:
            redirect = (
                f"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{target.port}/api/health\r\n"
                "Content-Length: 0\r\n\r\n"
            ).encode()
            with Hostile(lambda self, conn, req: conn.sendall(redirect)) as redirector:
                assert app_module.check_port(redirector.port) == "other"
            assert target.connections == 0

    @pytest.mark.parametrize(
        "status", ["301 Moved Permanently", "302 Found", "307 Temporary Redirect", "308 Permanent Redirect"]
    )
    def test_every_kind_of_redirect_counts_as_another_program(self, status):
        reply = f"HTTP/1.1 {status}\r\nLocation: http://elsewhere.invalid/\r\nContent-Length: 0\r\n\r\n".encode()
        with Hostile(lambda self, conn, req: conn.sendall(reply)) as server:
            # The suite's network guard turns any attempt to look up another host
            # into an error, so following the redirect would fail this test.
            assert app_module.check_port(server.port) == "other"


class TestTimeAndSizeLimits:
    def test_a_program_that_drips_its_answer_forever_is_given_up_on_in_time(self, quick):
        def drip(self, conn, req):
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 99999999\r\n\r\n")
            while not self.stopped:
                conn.sendall(b".")
                self.sleep(0.05)

        with Hostile(drip) as server:
            started = time.monotonic()
            assert app_module.check_port(server.port) == "other"
            assert time.monotonic() - started < quick + 1.5

    def test_a_program_that_drips_its_headers_forever_is_given_up_on_in_time(self, quick):
        def drip_headers(self, conn, req):
            conn.sendall(b"HTTP/1.1 200 OK\r\n")
            while not self.stopped:
                conn.sendall(b"X-Padding: x\r\n")
                self.sleep(0.05)

        with Hostile(drip_headers) as server:
            started = time.monotonic()
            assert app_module.check_port(server.port) == "other"
            assert time.monotonic() - started < quick + 1.5

    def test_a_program_that_accepts_but_never_answers_is_given_up_on_in_time(self, quick):
        with Hostile(lambda self, conn, req: self.sleep(30)) as server:
            started = time.monotonic()
            assert app_module.check_port(server.port) == "other"
            assert time.monotonic() - started < quick + 1.5

    def test_a_flood_of_data_is_cut_off_at_the_size_limit(self):
        sent = []

        def flood(self, conn, req):
            chunk = b"A" * 8192
            for _ in range(2000):  # 16 MB if it were all read
                conn.sendall(chunk)
                sent.append(len(chunk))

        with Hostile(flood) as server:
            started = time.monotonic()
            assert app_module.check_port(server.port) == "other"
            assert time.monotonic() - started < 3
        # It stopped reading, so the sender could not push anywhere near everything.
        assert sum(sent) < 16_000_000

    def test_the_genuine_answer_is_fast(self):
        with Hostile(lambda self, conn, req: conn.sendall(GENUINE)) as server:
            started = time.monotonic()
            assert app_module.check_port(server.port) == "ours"
            assert time.monotonic() - started < 1

    def test_a_slow_but_finishing_genuine_answer_is_still_recognized(self):
        def slowish(self, conn, req):
            self.sleep(0.4)
            conn.sendall(GENUINE)

        with Hostile(slowish) as server:
            assert app_module.check_port(server.port) == "ours"

    def test_the_limits_are_what_the_code_says_they_are(self):
        assert app_module.HEALTH_PROBE_SECONDS == 3
        assert app_module.HEALTH_PROBE_MAX_BYTES == 65536


class TestTheProbeItself:
    def test_proxy_settings_are_ignored(self, monkeypatch):
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:1")  # a proxy that is not there
        with Hostile(lambda self, conn, req: conn.sendall(GENUINE)) as server:
            assert app_module.check_port(server.port) == "ours"

    def test_it_sends_one_plain_get_for_the_health_path_over_one_connection(self):
        with Hostile(lambda self, conn, req: conn.sendall(GENUINE)) as server:
            app_module.check_port(server.port)
            assert server.connections == 1
            request = server.requests[0]
        assert request.startswith(b"GET /api/health HTTP/1.0\r\n")
        assert f"Host: 127.0.0.1:{server.port}\r\n".encode() in request
        assert b"Connection: close\r\n" in request
        assert request.endswith(b"\r\n\r\n")

    def test_a_connection_reset_midway_is_not_ours(self):
        def reset(self, conn, req):
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Le")
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")

        with Hostile(reset) as server:
            assert app_module.check_port(server.port) == "other"

    def test_nothing_listening_is_none(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        assert app_module.check_port(port) is None

    def test_the_real_app_is_recognized_with_the_raw_probe(self, monkeypatch):
        from werkzeug.serving import make_server

        server = make_server("127.0.0.1", 0, app_module.app, threaded=True)
        port = server.server_port
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert app_module.check_port(port) == "ours"
        finally:
            server.shutdown()
            thread.join(5)


class TestIsOurHealthReply:
    OURS = b'{"app": "lit-review"}'

    @pytest.mark.parametrize(
        "data",
        [
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + OURS,
            b"HTTP/1.0 200 OK\r\n\r\n" + OURS,
            b"HTTP/1.1 200\r\n\r\n" + OURS,
            b"HTTP/1.1 200 OK\r\nContent-Length: 22\r\n\r\n" + OURS + b"\n",
            b"HTTP/1.1 200 OK\r\n\r\n\xef\xbb\xbf" + OURS,
            b"HTTP/2 200\r\n\r\n" + OURS,
        ],
    )
    def test_accepted(self, data):
        assert app_module._is_our_health_reply(data) is True

    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"HTTP/1.1 200 OK\r\n\r\n",
            b"HTTP/1.1 200 OK",
            b"HTTP/1.1 200 OK\r\nContent-Type: x\r\n",  # the headers never end
            b"HTTP/1.1 404 Not Found\r\n\r\n" + OURS,
            b"HTTP/1.1 301 Moved\r\nLocation: /x\r\n\r\n" + OURS,
            b"HTTP/1.1 500 Oops\r\n\r\n" + OURS,
            b"HTTP/1.1 201 Created\r\n\r\n" + OURS,
            b"HTTP/1.1 2000 OK\r\n\r\n" + OURS,
            b"HTTP/1.1 abc\r\n\r\n" + OURS,
            b"FTP/1.1 200 OK\r\n\r\n" + OURS,
            b"220 hello\r\n\r\n" + OURS,
            b"\r\n\r\n" + OURS,
            b"HTTP/1.1 200 OK\r\n\r\n[]",
            b"HTTP/1.1 200 OK\r\n\r\nnull",
            b"HTTP/1.1 200 OK\r\n\r\n42",
            b'HTTP/1.1 200 OK\r\n\r\n{"app": "other"}',
            b'HTTP/1.1 200 OK\r\n\r\n{"app": ["lit-review"]}',
            b'HTTP/1.1 200 OK\r\n\r\n{"app": "Lit-Review"}',
            b'HTTP/1.1 200 OK\r\n\r\n{"app": "lit-review"',  # cut off
            b"HTTP/1.1 200 OK\r\n\r\n\xff\xfe\x00",
            b"HTTP/1.1 200 OK\r\n\r\n<html></html>",
        ],
    )
    def test_refused(self, data):
        assert app_module._is_our_health_reply(data) is False
