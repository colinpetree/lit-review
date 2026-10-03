"""Starting the app quickly. A port with nothing on it is the normal case on every
launch, so telling that apart from a held port must not wait for a refusal: on
Windows a closed loopback port takes 1 to 2 seconds to refuse a connection."""

import socket
import threading
import time

import pytest
from werkzeug.serving import make_server

import app as app_module
from test_startup import TestCheckPort

GENUINE = TestCheckPort.http_reply('{"app": "lit-review"}')

# What a free port may cost. The timeout is 0.25 s; the old wait was 1.0 s.
FAST = 0.6


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def dual_stack_available():
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind(("::", 0, 0, 0))
        return True
    except OSError:
        return False


class Holder:
    """A listener on a chosen address that answers every connection with `reply`
    (or never accepts, if reply is None)."""

    def __init__(self, address, reply=GENUINE, dual_stack=False):
        family = socket.AF_INET6 if dual_stack else socket.AF_INET
        self.listener = socket.socket(family, socket.SOCK_STREAM)
        if dual_stack:
            self.listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            self.listener.bind((address, 0, 0, 0))
        else:
            self.listener.bind((address, 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self.reply = reply
        self._stop = threading.Event()
        self._thread = None
        if reply is not None:
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()

    def _serve(self):
        self.listener.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except OSError:
                continue
            try:
                conn.settimeout(1)
                conn.recv(4096)
                conn.sendall(self.reply)
            except OSError:
                pass
            finally:
                conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        self.listener.close()


class TestAFreePortCostsAlmostNothing:
    def test_a_free_port_is_reported_as_nothing_running_quickly(self):
        port = free_port()
        started = time.perf_counter()
        assert app_module.check_port(port) is None
        assert time.perf_counter() - started < FAST

    def test_it_stays_quick_launch_after_launch(self):
        for _ in range(3):
            port = free_port()
            started = time.perf_counter()
            assert app_module.check_port(port) is None
            assert time.perf_counter() - started < FAST

    def test_the_connect_wait_is_the_short_one_not_the_old_second(self, monkeypatch):
        seen = []
        real = socket.create_connection

        def spy(address, timeout=None, *args, **kwargs):
            seen.append(timeout)
            return real(address, timeout, *args, **kwargs)

        monkeypatch.setattr(app_module.socket, "create_connection", spy)
        app_module.check_port(free_port())
        assert seen == [app_module.PORT_CONNECT_SECONDS]
        assert app_module.PORT_CONNECT_SECONDS <= 0.5

    def test_a_listener_accepts_far_inside_that_wait(self):
        """The margin the short timeout relies on: connecting to a listener takes
        milliseconds, even one that never accepts."""
        with Holder("127.0.0.1", reply=None) as holder:
            started = time.perf_counter()
            socket.create_connection(("127.0.0.1", holder.port), timeout=app_module.PORT_CONNECT_SECONDS).close()
            assert time.perf_counter() - started < app_module.PORT_CONNECT_SECONDS / 4

    def test_the_port_is_left_free_for_the_server_to_take_straight_after(self):
        port = free_port()
        assert app_module.check_port(port) is None
        server = make_server("127.0.0.1", port, app_module.app, threaded=True)
        try:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            # A second launch now finds it held.
            assert app_module.check_port(port) is not None
        finally:
            server.shutdown()
            server.server_close()


class TestEveryKindOfHolderIsStillSeen:
    """Binding the port to test it would call some of these free (a program on
    all interfaces, or on dual-stack IPv6, is invisible to a bind on 127.0.0.1)
    and the app would then start on top of it. Connecting sees them all."""

    def test_a_listener_on_loopback(self):
        with Holder("127.0.0.1") as holder:
            assert app_module.check_port(holder.port) == "ours"

    def test_a_listener_on_every_interface(self):
        with Holder("0.0.0.0") as holder:
            assert app_module.check_port(holder.port) == "ours"

    @pytest.mark.skipif(not dual_stack_available(), reason="no dual-stack IPv6 here")
    def test_a_dual_stack_ipv6_listener(self):
        with Holder("::", dual_stack=True) as holder:
            assert app_module.check_port(holder.port) == "ours"

    def test_another_program_on_every_interface_is_in_use_not_free(self):
        with Holder("0.0.0.0", reply=b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi") as holder:
            assert app_module.check_port(holder.port) == "other"

    def test_a_listener_that_never_accepts_is_in_use_not_free(self, monkeypatch):
        monkeypatch.setattr(app_module, "HEALTH_PROBE_SECONDS", 1)
        with Holder("127.0.0.1", reply=None) as holder:
            assert app_module.check_port(holder.port) == "other"

    def test_a_socket_bound_but_never_listening_is_not_a_running_app(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        try:
            assert app_module.check_port(sock.getsockname()[1]) is None
        finally:
            sock.close()

    def test_this_app_running_is_recognized_quickly(self, monkeypatch):
        server = make_server("127.0.0.1", 0, app_module.app, threaded=True)
        port = server.server_port
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            started = time.perf_counter()
            assert app_module.check_port(port) == "ours"
            assert time.perf_counter() - started < 1
        finally:
            server.shutdown()
            server.server_close()
