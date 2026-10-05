"""The autouse fixtures in conftest.py are what keep tests away from the real
data, so they get tests of their own."""

import os
import socket

import pytest

import credentials
import db


def test_database_is_in_the_temp_dir(isolated_data):
    assert db.list_datasets() == []
    assert db.DB_PATH.is_file()
    assert str(db.DB_PATH).startswith(str(isolated_data))


def test_credentials_are_in_the_temp_dir(isolated_data):
    credentials.set_key("anthropic", "sk-test")
    assert credentials.has_key("anthropic")
    assert credentials.get_key("anthropic") == "sk-test"
    assert credentials.STORE_FILE.is_file()
    assert str(credentials.STORE_FILE).startswith(str(isolated_data))


def test_env_keys_do_not_leak_into_tests():
    assert os.environ.get("ANTHROPIC_API_KEY") is None
    assert not credentials.has_key("anthropic")


def test_client_fixture_talks_to_the_app_on_its_real_host(client):
    response = client.get("/api/datasets")
    assert response.status_code == 200
    assert response.get_json() == {"datasets": []}
    assert response.request.host == "127.0.0.1:8100"


OUTSIDE = ("93.184.216.34", 80)


def test_outside_connections_are_blocked():
    with pytest.raises(RuntimeError, match="reach the network"):
        socket.create_connection(OUTSIDE, timeout=1)


def test_non_blocking_connects_are_blocked_too():
    sock = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="connect_ex"):
            sock.connect_ex(OUTSIDE)
    finally:
        sock.close()


def test_udp_sends_are_blocked():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(RuntimeError, match="sendto"):
            sock.sendto(b"x", OUTSIDE)
    finally:
        sock.close()


def test_hostname_lookups_are_blocked_so_results_do_not_depend_on_internet_access():
    with pytest.raises(RuntimeError, match="DNS lookup"):
        socket.getaddrinfo("example.com", 443)


def test_loopback_is_still_allowed():
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo("127.0.0.1", 80)


@pytest.mark.parametrize("url", ["https://example.com", "http://93.184.216.34"])
def test_provider_sdk_traffic_is_blocked(url):
    import httpx

    # RuntimeError specifically: any other error (such as a DNS failure while
    # offline) would mean the guard was not what stopped the request.
    with pytest.raises(RuntimeError, match="reach the network"):
        httpx.get(url, timeout=1)


def test_requests_library_traffic_is_blocked():
    import requests

    with pytest.raises(RuntimeError, match="reach the network"):
        requests.get("https://example.com", timeout=1)
