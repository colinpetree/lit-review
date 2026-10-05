"""Starting a second copy of the app, and the health check that lets it tell."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from werkzeug.serving import make_server

import app as app_module


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestHealthRoute:
    def test_it_identifies_the_app(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.get_json()
        assert body["app"] == "lit-review"
        assert body["instance"] == app_module.INSTANCE_ID
        assert set(body) == {"app", "instance"}  # nothing private rides along

    def test_it_is_behind_the_request_guard(self, client):
        assert client.get("/api/health", base_url="http://evil.example:8100").status_code == 403


class TestCheckPort:
    def test_nothing_listening(self):
        assert app_module.check_port(free_port()) is None

    def test_this_app_is_recognized(self, monkeypatch):
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

    def test_another_web_server_is_not_ours(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"app": "something-else"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert app_module.check_port(server.server_port) == "other"
        finally:
            server.shutdown()
            thread.join(5)

    def test_a_server_that_is_not_http_is_not_ours(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        stop = threading.Event()

        def accept_and_hang_up():
            listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    conn, _ = listener.accept()
                except OSError:
                    continue
                conn.close()

        thread = threading.Thread(target=accept_and_hang_up, daemon=True)
        thread.start()
        try:
            assert app_module.check_port(listener.getsockname()[1]) == "other"
        finally:
            stop.set()
            thread.join(5)
            listener.close()

    @staticmethod
    def raw_server(reply):
        """A listener that answers every connection with exactly `reply` bytes
        (after reading the request) and hangs up. Returns (port, stop)."""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        stop = threading.Event()

        def serve():
            listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    conn, _ = listener.accept()
                except OSError:
                    continue
                try:
                    conn.settimeout(0.5)
                    try:
                        conn.recv(4096)
                    except OSError:
                        pass
                    conn.sendall(reply)
                except OSError:
                    pass
                finally:
                    conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        def shut_down():
            stop.set()
            thread.join(5)
            listener.close()

        return listener.getsockname()[1], shut_down

    @staticmethod
    def http_reply(body, status="200 OK", content_type="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        head = f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {len(data)}\r\n\r\n"
        return head.encode() + data

    @pytest.mark.parametrize(
        "reply",
        [
            pytest.param(b"220 mail.example ESMTP ready\r\n", id="text banner (not HTTP)"),
            pytest.param(b"SSH-2.0-OpenSSH_9.0\r\n", id="ssh banner"),
            pytest.param(b"\x00\x01\x02\xff\xfe", id="binary junk"),
            pytest.param(b"HTTP/1.1 abc\r\n\r\n", id="malformed status line"),
            pytest.param(b"HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\nshort", id="body shorter than promised"),
            pytest.param(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n", id="broken chunked body"),
            pytest.param(b"", id="hangs up without answering"),
        ],
    )
    def test_a_program_that_does_not_speak_http_is_reported_not_crashed_on(self, reply):
        port, stop = self.raw_server(reply)
        try:
            assert app_module.check_port(port) == "other"
        finally:
            stop()

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("[]", id="json list"),
            pytest.param('"lit-review"', id="json string"),
            pytest.param("null", id="json null"),
            pytest.param("42", id="json number"),
            pytest.param("true", id="json boolean"),
            pytest.param("{}", id="empty object"),
            pytest.param('{"app": null}', id="app is null"),
            pytest.param('{"app": ["lit-review"]}', id="app is a list"),
            pytest.param('{"app": "Lit-Review"}', id="wrong case"),
            pytest.param("<html>hello</html>", id="html page"),
            pytest.param("{not json", id="broken json"),
            pytest.param("", id="empty body"),
            pytest.param("\xff\xfe".encode("latin-1"), id="not valid utf-8"),
        ],
    )
    def test_a_web_server_that_does_not_answer_as_this_app_is_not_ours(self, body):
        port, stop = self.raw_server(self.http_reply(body))
        try:
            assert app_module.check_port(port) == "other"
        finally:
            stop()

    @pytest.mark.parametrize("status", ["404 Not Found", "403 Forbidden", "500 Internal Server Error", "301 Moved Permanently"])
    def test_an_http_error_status_is_not_ours(self, status):
        port, stop = self.raw_server(self.http_reply('{"app": "lit-review"}', status=status))
        try:
            assert app_module.check_port(port) == "other"
        finally:
            stop()

    def test_an_endless_reply_is_not_read_without_limit(self):
        # Declares far more body than it sends, then hangs up: must not hang or blow up.
        head = b"HTTP/1.1 200 OK\r\nContent-Length: 999999999\r\n\r\n" + b"x" * 200_000
        port, stop = self.raw_server(head)
        try:
            assert app_module.check_port(port) == "other"
        finally:
            stop()

    def test_the_exact_reply_this_app_gives_is_recognized(self):
        port, stop = self.raw_server(self.http_reply('{"app": "lit-review"}'))
        try:
            assert app_module.check_port(port) == "ours"
        finally:
            stop()

    def test_an_older_copy_without_the_health_route_counts_as_another_program(self, monkeypatch):
        # Same server, but with the route answering 404, as in a version from
        # before it existed. setitem puts the real view back after the test.
        monkeypatch.setitem(app_module.app.view_functions, "health", lambda: ({"error": "not found"}, 404))
        server = make_server("127.0.0.1", 0, app_module.app, threaded=True)
        port = server.server_port
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert app_module.check_port(port) == "other"
        finally:
            server.shutdown()
            thread.join(5)

    def test_the_real_health_route_is_back_after_that(self, client):
        assert client.get("/api/health").get_json()["app"] == "lit-review"
