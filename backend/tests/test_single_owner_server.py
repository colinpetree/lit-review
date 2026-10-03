"""The server refuses a port that is already in use, instead of silently sharing it
(which Werkzeug's default socket options allow on Windows)."""

import socket
import threading
import time

import pytest

import app as app_module
from app import PortTaken, SingleOwnerServer
from procutil import free_port


def wsgi(environ, start_response):
    if environ["PATH_INFO"] == "/slow":
        time.sleep(1)
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", "2")])
    return [b"ok"]


def serve(port):
    server = SingleOwnerServer("127.0.0.1", port, wsgi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


def get(port, path="/"):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(f"GET {path} HTTP/1.0\r\nHost: x\r\n\r\n".encode())
        data = b""
        while chunk := sock.recv(4096):
            data += chunk
    return data.split(b"\r\n\r\n", 1)[1]


class TestRefusesAPortInUse:
    def test_a_second_server_cannot_take_a_port_a_first_one_holds(self):
        port = free_port()
        first, thread = serve(port)
        try:
            with pytest.raises(PortTaken):
                SingleOwnerServer("127.0.0.1", port, wsgi)
            assert get(port) == b"ok"  # and the first one is undisturbed
        finally:
            stop(first, thread)

    def test_the_refusal_is_a_catchable_signal_not_an_exit_or_a_raw_access_denied(self, capsys):
        """Windows reports a port held exclusively as "access denied" (and Werkzeug
        would print that and exit); the caller needs to be able to try the next port."""
        port = free_port()
        first, thread = serve(port)
        try:
            with pytest.raises(PortTaken) as refused:
                SingleOwnerServer("127.0.0.1", port, wsgi)
            assert str(port) in str(refused.value)
            assert not isinstance(refused.value, (SystemExit, OSError))
            captured = capsys.readouterr()
            assert "forbidden by its access permissions" not in captured.err + captured.out
        finally:
            stop(first, thread)

    def test_a_refused_attempt_does_not_leave_a_socket_behind(self):
        port = free_port()
        first, thread = serve(port)
        try:
            for _ in range(20):  # a leak per refusal would pile up
                with pytest.raises(PortTaken):
                    SingleOwnerServer("127.0.0.1", port, wsgi)
        finally:
            stop(first, thread)
        # and once the owner has gone the port is simply usable again
        again, thread = serve(port)
        stop(again, thread)

    def test_other_bind_problems_are_not_mistaken_for_a_taken_port(self):
        """An address that cannot be bound at all is a different error and must say so."""
        with pytest.raises(Exception) as problem:
            SingleOwnerServer("203.0.113.1", free_port(), wsgi)  # not an address of this machine
        assert not isinstance(problem.value, PortTaken)

    def test_it_refuses_a_port_held_by_a_plain_listener(self):
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        try:
            with pytest.raises(PortTaken):
                SingleOwnerServer("127.0.0.1", holder.getsockname()[1], wsgi)
        finally:
            holder.close()

    def test_it_refuses_a_port_held_by_a_program_that_set_reuse_address(self):
        """What Werkzeug's own default server does on Windows: the case this exists for."""
        holder = socket.socket()
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        try:
            with pytest.raises(PortTaken):
                SingleOwnerServer("127.0.0.1", holder.getsockname()[1], wsgi)
        finally:
            holder.close()

    def test_the_default_server_would_have_shared_the_port_on_windows(self):
        """The reason for all this, shown on the platform where it happens: two of
        Werkzeug's default servers both bind the port, with no error."""
        if not hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            pytest.skip("only Windows lets a second listener share a port")
        from werkzeug.serving import ThreadedWSGIServer

        port = free_port()
        first = ThreadedWSGIServer("127.0.0.1", port, wsgi)
        thread = threading.Thread(target=first.serve_forever, daemon=True)
        thread.start()
        try:
            second = ThreadedWSGIServer("127.0.0.1", port, wsgi)  # no error: the silent second copy
            second.server_close()
            # Ours is not fooled: it refuses a port held by a default server.
            with pytest.raises(PortTaken):
                SingleOwnerServer("127.0.0.1", port, wsgi)
        finally:
            stop(first, thread)


class TestRestartsAtOnce:
    def test_the_same_port_can_be_used_again_straight_after_stopping(self):
        port = free_port()
        first, thread = serve(port)
        for _ in range(25):  # the server closes each connection first, leaving them waiting to close
            assert get(port) == b"ok"
        stop(first, thread)

        second, thread = serve(port)
        try:
            assert get(port) == b"ok"
        finally:
            stop(second, thread)

    def test_and_again_and_again(self):
        port = free_port()
        for _ in range(4):
            server, thread = serve(port)
            assert get(port) == b"ok"
            stop(server, thread)


class TestOptions:
    def test_reuse_address_is_off_exactly_where_the_exclusive_flag_exists(self):
        assert SingleOwnerServer.allow_reuse_address == (not hasattr(socket, "SO_EXCLUSIVEADDRUSE"))

    @pytest.mark.skipif(not hasattr(socket, "SO_EXCLUSIVEADDRUSE"), reason="Windows only")
    def test_the_exclusive_flag_is_set_on_windows(self):
        port = free_port()
        server, thread = serve(port)
        try:
            assert server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) == 1
            assert server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        finally:
            stop(server, thread)

    def test_it_is_threaded_so_a_slow_request_does_not_block_another(self):
        port = free_port()
        server, thread = serve(port)
        try:
            slow = threading.Thread(target=get, args=(port, "/slow"))
            slow.start()
            time.sleep(0.2)
            started = time.perf_counter()
            assert get(port) == b"ok"
            assert time.perf_counter() - started < 0.7  # did not wait for the 1 s request
            slow.join(5)
        finally:
            stop(server, thread)

    def test_it_serves_the_real_app(self, monkeypatch):
        port = free_port()
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        server = SingleOwnerServer("127.0.0.1", port, app_module.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert app_module.check_port(port) == "ours"
        finally:
            stop(server, thread)
