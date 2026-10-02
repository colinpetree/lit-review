"""Shared fixtures. Two of them are autouse safety nets, so no test can touch
the real database or saved API keys, or reach the network, even by mistake."""

import ipaddress
import socket

import pytest

import credentials
import db
import llm


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Point the database and the credential store at a temp dir."""
    config_dir = tmp_path / "config"
    monkeypatch.setattr(credentials, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(credentials, "KEY_FILE", config_dir / "credentials.key")
    monkeypatch.setattr(credentials, "STORE_FILE", config_dir / "credentials.enc")
    monkeypatch.setattr(credentials, "LOCK_FILE", config_dir / "credentials.lock")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "lit_review.db")
    # A key in the developer's shell must not leak into a test.
    for name in ("ANTHROPIC", "OPENAI", "GEMINI", "OPENALEX", "ELSEVIER", "SPRINGERNATURE", "SEMANTICSCHOLAR"):
        monkeypatch.delenv(f"{name}_API_KEY", raising=False)
    return tmp_path


def _is_local(host):
    if host is None or host == "":
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail any attempt to reach somewhere other than this machine: connecting
    (blocking or not), sending a UDP datagram, or looking up a hostname. This
    catches the provider SDKs too (they use httpx, not requests). Looking up the
    name is blocked as well, so a test fails the same way with or without
    internet access."""
    real = {
        "connect": socket.socket.connect,
        "connect_ex": socket.socket.connect_ex,
        "sendto": socket.socket.sendto,
        "getaddrinfo": socket.getaddrinfo,
    }

    def refuse(what, target):
        raise RuntimeError(f"Test tried to reach the network ({what}: {target!r})")

    def connect(self, address):
        if not _is_local(address[0] if isinstance(address, tuple) else address):
            refuse("connect", address)
        return real["connect"](self, address)

    def connect_ex(self, address):
        if not _is_local(address[0] if isinstance(address, tuple) else address):
            refuse("connect_ex", address)
        return real["connect_ex"](self, address)

    def sendto(self, data, *args):
        address = args[-1]
        if not _is_local(address[0] if isinstance(address, tuple) else address):
            refuse("sendto", address)
        return real["sendto"](self, data, *args)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            refuse("DNS lookup", host)
        return real["getaddrinfo"](host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def client(monkeypatch):
    """A Flask test client that sends the Host the real app is served on."""
    import app as app_module
    from flask.testing import FlaskClient

    class LocalClient(FlaskClient):
        def open(self, *args, **kwargs):
            kwargs.setdefault("base_url", f"http://127.0.0.1:{app_module.PORT}")
            return super().open(*args, **kwargs)

    monkeypatch.setattr(app_module.app, "test_client_class", LocalClient)
    return app_module.app.test_client()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the provider call. `respond(system, user, schema)` returns the
    parsed JSON the model would have produced. Every call is recorded in
    `fake.calls`."""

    class Fake:
        def __init__(self):
            self.calls = []
            self.respond = lambda system, user, schema: {}
            self.input_tokens = 100
            self.output_tokens = 50

    fake = Fake()

    def complete(ai_api, model, system, user, schema, max_tokens):
        fake.calls.append({"ai_api": ai_api, "model": model, "system": system, "user": user, "schema": schema})
        parsed = fake.respond(system, user, schema)
        return parsed, llm.Usage(fake.input_tokens, fake.output_tokens, model=model, provider=ai_api)

    monkeypatch.setattr(llm, "_complete_json", complete)
    return fake
