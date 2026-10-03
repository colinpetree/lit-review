"""Launching the app more than once, for real: separate `python app.py` processes
with their own temp data, on spare ports. Never the real port, never real data.

One user, one app: a second launch by the same user opens a browser on the copy
already running (signed in) and exits, and two launches at the same moment end
with exactly one app. Two users are two data folders: each gets their own copy on
its own port, and neither can use the other's."""

import http.client
import socket
import threading
import time
from urllib.parse import urlparse

import pytest

import app as app_module
from app import SingleOwnerServer
from procutil import Copy, free_port, free_port_run

START_TIMEOUT = 30
HAND_OVER_TIMEOUT = 20


@pytest.fixture
def launcher(tmp_path):
    """Starts copies, asked to use one spare port. `user` chooses the data folder
    (so which lock, secret and record a copy has: one folder is one user);
    copies are always killed afterwards."""
    port = free_port_run(8)
    started = []

    def launch(user="alice"):
        copy = Copy(port, tmp_path / user / "data", tmp_path / user / "config")
        started.append(copy)
        return copy

    launch.port = port
    yield launch
    for copy in started:
        copy.kill()


def http_get(port, path, token=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = dict(headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def would_open(copy):
    """The address a copy said it would open in the browser, as (port, token): the
    private link, with the secret in the fragment (so no server is ever sent it)."""
    line = next(l for l in copy.output.splitlines() if l.startswith("Would open "))
    parsed = urlparse(line[len("Would open "):].strip())
    assert parsed.path == "/" and parsed.query == ""
    assert parsed.fragment.startswith("token=")
    return parsed.port, parsed.fragment[len("token="):]


class TestOneUsersSecondLaunch:
    def test_the_first_launch_starts_the_app_and_makes_the_secret(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        assert first.port == launcher.port
        assert len(first.token) >= 43
        assert f"/#token={first.token}" in first.output  # the private link, if no browser opens

    def test_a_second_launch_opens_a_signed_in_browser_on_the_first_and_starts_nothing(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output

        second = launcher()
        assert second.wait_exit(HAND_OVER_TIMEOUT) == 0, second.output

        assert "already running" in second.output
        assert "is running at" not in second.output  # no second app
        port, token = would_open(second)
        assert port == first.port
        assert token == first.token  # the link that signs the browser in to that copy
        assert first.alive()
        assert app_module.check_port(first.port) == "ours"

    def test_it_does_not_matter_how_many_times_it_is_launched(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        for copy in [launcher() for _ in range(3)]:
            assert copy.wait_exit(HAND_OVER_TIMEOUT) == 0, copy.output
            assert would_open(copy) == (first.port, first.token)
            assert "is running at" not in copy.output
        assert first.alive()
        assert first.output.count("is running at") == 1

    def test_the_second_launch_is_quick_once_the_first_is_up(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        started = time.monotonic()
        assert launcher().wait_exit(HAND_OVER_TIMEOUT) == 0
        assert time.monotonic() - started < 10  # process start dominates; it never waits out a timeout

    def test_the_first_copy_keeps_serving_after_the_second_has_come_and_gone(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        launcher().wait_exit(HAND_OVER_TIMEOUT)
        assert first.alive()
        assert app_module.check_port(first.port) == "ours"

    def test_the_secret_is_the_same_after_a_restart_so_bookmarks_and_cookies_keep_working(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        secret = first.token
        first.kill()

        second = launcher()
        assert second.wait_serving(START_TIMEOUT), second.output
        assert second.token == secret


class TestTwoLaunchesAtTheSameMoment:
    def test_exactly_one_app_ends_up_running(self, launcher):
        copies = [launcher() for _ in range(4)]  # back to back, before any has bound a port

        assert any(c.wait_serving(START_TIMEOUT) for c in copies), [c.output for c in copies]
        for copy in copies:
            copy.wait_exit(HAND_OVER_TIMEOUT)  # the losers hand over and exit; the winner keeps running

        running = [c for c in copies if c.alive()]
        assert len(running) == 1, [c.output for c in copies]
        winner = running[0]
        assert winner.output.count("is running at") == 1
        for loser in (c for c in copies if c is not winner):
            assert loser.wait_exit(1) == 0, loser.output
            assert "already running" in loser.output
            assert "is running at" not in loser.output
            assert would_open(loser) == (winner.port, winner.token)
        assert app_module.check_port(winner.port) == "ours"

    def test_a_copy_that_starts_while_another_is_still_starting_waits_for_it(self, launcher):
        first = launcher()
        second = launcher()  # at once: the first has the lock but has not bound its port yet
        assert first.wait_serving(START_TIMEOUT) or second.wait_serving(START_TIMEOUT)
        codes = [c.wait_exit(HAND_OVER_TIMEOUT) for c in (first, second)]
        assert sorted(code for code in codes if code is not None) == [0]
        assert len([c for c in (first, second) if c.alive()]) == 1


class TestTwoUsersOnOneComputer:
    """Two data folders stand for two accounts: separate locks and secrets, one machine-wide port space."""

    def test_the_second_user_gets_their_own_app_on_the_next_port(self, launcher):
        alice = launcher("alice")
        assert alice.wait_serving(START_TIMEOUT), alice.output
        bob = launcher("bob")
        assert bob.wait_serving(START_TIMEOUT), bob.output

        assert alice.port == launcher.port
        assert bob.port == launcher.port + 1
        assert alice.alive() and bob.alive()
        assert alice.token != bob.token
        assert "already running" not in bob.output

    def test_neither_user_can_use_the_others_app(self, launcher):
        alice, bob = launcher("alice"), launcher("bob")
        assert alice.wait_serving(START_TIMEOUT) and bob.wait_serving(START_TIMEOUT)

        # Bob's browser holds Bob's secret, which works on Bob's app...
        assert http_get(bob.port, "/api/datasets", token=bob.token)[0] == 200
        # ...and has nothing that works on Alice's, whichever way he tries.
        assert http_get(alice.port, "/api/datasets", token=bob.token)[0] == 401
        assert http_get(alice.port, "/api/datasets")[0] == 401
        assert http_get(alice.port, f"/api/datasets?token={bob.token}")[0] == 401
        assert http_get(alice.port, f"/api/datasets?token={alice.token}")[0] == 401  # not even the right one, in the address
        # And the other way round.
        assert http_get(alice.port, "/api/datasets", token=alice.token)[0] == 200
        assert http_get(bob.port, "/api/datasets", token=alice.token)[0] == 401

    def test_a_users_second_launch_finds_their_own_copy_not_the_other_users(self, launcher):
        alice = launcher("alice")
        assert alice.wait_serving(START_TIMEOUT), alice.output
        bob = launcher("bob")
        assert bob.wait_serving(START_TIMEOUT), bob.output

        bob_again = launcher("bob")
        assert bob_again.wait_exit(HAND_OVER_TIMEOUT) == 0, bob_again.output
        assert would_open(bob_again) == (bob.port, bob.token)  # Bob's, on Bob's port

        alice_again = launcher("alice")
        assert alice_again.wait_exit(HAND_OVER_TIMEOUT) == 0, alice_again.output
        assert would_open(alice_again) == (alice.port, alice.token)

    def test_three_users_each_get_a_copy(self, launcher):
        copies = [launcher(name) for name in ("alice", "bob", "carol")]
        assert all(c.wait_serving(START_TIMEOUT) for c in copies), [c.output for c in copies]
        assert sorted(c.port for c in copies) == [launcher.port, launcher.port + 1, launcher.port + 2]
        assert len({c.token for c in copies}) == 3


class TestAPortThatIsTaken:
    def occupy(self, port):
        listener = socket.socket()
        listener.bind(("127.0.0.1", port))
        listener.listen(5)
        stop = threading.Event()

        def hang_up_on_everyone():
            listener.settimeout(0.1)
            while not stop.is_set():
                try:
                    conn, _ = listener.accept()
                    conn.close()
                except OSError:
                    pass

        thread = threading.Thread(target=hang_up_on_everyone, daemon=True)
        thread.start()

        def release():
            stop.set()
            thread.join(5)
            listener.close()

        return release

    def test_another_program_on_the_default_port_means_the_next_one_is_used(self, launcher):
        release = self.occupy(launcher.port)
        try:
            copy = launcher()
            assert copy.wait_serving(START_TIMEOUT), copy.output
            assert copy.port == launcher.port + 1
        finally:
            release()

    def test_a_second_launch_by_the_same_user_finds_the_copy_on_the_other_port(self, launcher):
        release = self.occupy(launcher.port)
        try:
            first = launcher()
            assert first.wait_serving(START_TIMEOUT), first.output
            assert first.port == launcher.port + 1

            second = launcher()
            assert second.wait_exit(HAND_OVER_TIMEOUT) == 0, second.output
            assert would_open(second) == (first.port, first.token)  # not the default port
            assert "is running at" not in second.output
        finally:
            release()

    def test_a_copy_started_some_other_way_on_the_default_port_is_just_another_copy(self, launcher, monkeypatch):
        """One that holds no lock and has a different secret: not this user's, so it is
        stepped around rather than opened."""
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", {f"127.0.0.1:{launcher.port}"})
        other = SingleOwnerServer("127.0.0.1", launcher.port, app_module.app)
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            copy = launcher()
            assert copy.wait_serving(START_TIMEOUT), copy.output
            assert copy.port == launcher.port + 1
            assert app_module.check_port(launcher.port) == "ours"  # and it is still there
        finally:
            other.shutdown()
            other.server_close()
            thread.join(5)


class TestTheSecretOnTheWire:
    def test_only_the_header_connects_a_browser_and_nothing_else_does(self, launcher):
        copy = launcher()
        assert copy.wait_serving(START_TIMEOUT), copy.output
        port, token = copy.port, copy.token

        # The page is open: it holds nothing private, and reads the secret from its address.
        status, _, body = http_get(port, "/")
        assert status in (200, 404)  # served, or a plain 404 where no build exists; never refused
        assert token.encode() not in body

        # The data is closed to anyone without the secret in a header.
        assert http_get(port, "/api/datasets")[0] == 401
        assert http_get(port, f"/api/datasets?token={token}")[0] == 401
        assert http_get(port, "/api/datasets", headers={"Cookie": f"lr_session={token}; token={token}"})[0] == 401
        assert http_get(port, "/api/datasets", headers={"X-Token": token})[0] == 401
        assert http_get(port, "/api/datasets", token="wrong" * 10)[0] == 401

        # With the secret in the header it works.
        assert http_get(port, "/api/datasets", token=token)[0] == 200

    def test_nothing_the_app_sends_ever_sets_a_cookie(self, launcher):
        copy = launcher()
        assert copy.wait_serving(START_TIMEOUT), copy.output
        for path in ("/", "/api/health", "/api/datasets", "/nowhere"):
            for token in (None, copy.token):
                _, headers, _ = http_get(copy.port, path, token=token)
                assert "Set-Cookie" not in headers

    def test_the_health_answer_names_the_copy_the_record_points_at(self, launcher):
        import json

        copy = launcher()
        assert copy.wait_serving(START_TIMEOUT), copy.output
        status, _, body = http_get(copy.port, "/api/health")
        record = json.loads((copy.data_dir / "instance.json").read_text(encoding="utf-8"))
        assert status == 200
        assert json.loads(body)["instance"] == record["id"]
        assert record["port"] == copy.port

    def test_the_secret_is_never_in_what_the_app_serves_to_a_stranger(self, launcher):
        copy = launcher()
        assert copy.wait_serving(START_TIMEOUT), copy.output
        for path in ("/", "/api/datasets", "/api/health", "/auth?token=nope", "/nowhere"):
            status, headers, body = http_get(copy.port, path)
            assert copy.token.encode() not in body
            assert copy.token not in str(headers)

    def test_the_secret_never_appears_in_a_request_the_app_receives(self, launcher):
        """The private link keeps it in the fragment, which a browser never sends: so the
        app's own log of requests cannot contain it."""
        copy = launcher()
        assert copy.wait_serving(START_TIMEOUT), copy.output
        http_get(copy.port, "/", token=copy.token)
        http_get(copy.port, "/api/datasets", token=copy.token)
        time.sleep(0.3)
        log_lines = [l for l in copy.output.splitlines() if '"GET ' in l or '"POST ' in l]
        assert log_lines  # requests were logged...
        assert not any(copy.token in l for l in log_lines)  # ...and none holds the secret


class TestAnOlderCopyStillRunning:
    """Updating while the previous version is running: it holds the lock but writes no
    record and never asks for a secret."""

    def start_older_copy(self, launcher, tmp_path):
        import subprocess
        import sys

        from procutil import BACKEND_DIR

        data = tmp_path / "alice" / "data"
        script = tmp_path / "older.py"
        script.write_text(
            "import sys, json, http.server\n"
            "sys.path.insert(0, sys.argv[3])\n"
            "import single_instance\n"
            "lock = single_instance.acquire(sys.argv[1] + '/instance.lock')\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        body = json.dumps({'app': 'lit-review'}).encode()\n"
            "        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)\n"
            "    def log_message(self, *a): pass\n"
            "http.server.HTTPServer(('127.0.0.1', int(sys.argv[2])), H).serve_forever()\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen([sys.executable, str(script), str(data), str(launcher.port), str(BACKEND_DIR)])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and app_module.check_port(launcher.port) != "ours":
            time.sleep(0.2)
        assert app_module.check_port(launcher.port) == "ours"
        return proc

    def test_a_launch_opens_the_older_copy_instead_of_waiting_and_failing(self, launcher, tmp_path):
        from procutil import kill_tree

        older = self.start_older_copy(launcher, tmp_path)
        try:
            started = time.monotonic()
            copy = launcher()  # same data folder, so the same lock
            code = copy.wait_exit(HAND_OVER_TIMEOUT)
            elapsed = time.monotonic() - started

            assert code == 0, copy.output
            assert "older version of Lit Review is already running" in copy.output
            assert f"Would open http://127.0.0.1:{launcher.port}" in copy.output
            assert "#token=" not in copy.output  # the older copy asks for no secret
            assert "is running at" not in copy.output  # and nothing new was started
            assert elapsed < app_module.RUNNING_COPY_WAIT_SECONDS  # it did not wait out the full time
        finally:
            kill_tree(older)


class TestACopyThatDies:
    def test_a_killed_copy_leaves_nothing_that_blocks_the_next_launch(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        first.kill()  # a hard kill: no chance to clean up (its record stays behind)
        assert not first.alive()
        assert (first.data_dir / "instance.json").exists()

        second = launcher()
        assert second.wait_serving(START_TIMEOUT), second.output
        assert "is running at" in second.output
        assert second.port == launcher.port  # the port it left is free again

    def test_a_stale_record_never_sends_a_launch_to_the_wrong_place(self, launcher):
        first = launcher()
        assert first.wait_serving(START_TIMEOUT), first.output
        first.kill()
        second = launcher()
        assert second.wait_serving(START_TIMEOUT), second.output

        third = launcher()
        assert third.wait_exit(HAND_OVER_TIMEOUT) == 0, third.output
        assert would_open(third) == (second.port, second.token)
        assert second.alive()


class TestAnUnusableDataFolder:
    def run(self, launcher, tmp_path, data_dir):
        copy = Copy(launcher.port, data_dir, tmp_path / "config")
        try:
            code = copy.wait_exit(30)
            return code, copy.output
        finally:
            copy.kill()

    def test_a_folder_that_cannot_be_created_is_explained_not_a_traceback(self, launcher, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where a folder should be")
        code, output = self.run(launcher, tmp_path, blocker / "data")

        assert code == 1
        assert "cannot use its data folder" in output
        assert str(blocker) in output
        assert "Make sure that folder can be written to" in output
        assert "Traceback" not in output
        assert "is running at" not in output

    def test_a_database_that_cannot_be_opened_is_explained_not_a_traceback(self, launcher, tmp_path):
        data_dir = tmp_path / "data"
        (data_dir / "lit_review.db").mkdir(parents=True)  # a folder where the database file should be
        code, output = self.run(launcher, tmp_path, data_dir)

        assert code == 1
        assert "cannot use its data folder" in output
        assert "Traceback" not in output

    def test_nothing_is_left_holding_the_port_or_the_lock_afterwards(self, launcher, tmp_path):
        self.run(launcher, tmp_path, tmp_path / "blocker-file" / "data") if False else None
        data_dir = tmp_path / "data"
        (data_dir / "lit_review.db").mkdir(parents=True)
        code, _ = self.run(launcher, tmp_path, data_dir)
        assert code == 1
        assert app_module.check_port(launcher.port) is None
        # Fix the folder: the very next launch works.
        (data_dir / "lit_review.db").rmdir()
        fixed = Copy(launcher.port, data_dir, tmp_path / "config")
        try:
            assert fixed.wait_serving(START_TIMEOUT), fixed.output
        finally:
            fixed.kill()


def http_call(port, method, path, token, body=None, content_type=None):
    """One request to a real copy; returns (status, body bytes). A fresh connection each time."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


class TestBackupAndRestoreThroughARealServer:
    """The restore reads its body straight off the connection, past the 1 MB limit the test
    client does not exercise, so it is checked against a real server."""

    def test_a_backup_downloaded_from_a_real_copy_restores_into_it(self, launcher, tmp_path):
        import json
        import sqlite3
        from contextlib import closing

        copy = launcher()
        assert copy.wait_serving(START_TIMEOUT), copy.output
        port, token = copy.port, copy.token

        def prompts():
            status, body = http_call(port, "GET", "/api/prompts", token)
            assert status == 200
            return [p["name"] for p in json.loads(body)["prompts"]]

        def add_prompt(name):
            status, _ = http_call(
                port, "POST", "/api/prompts", token, json.dumps({"name": name, "description": "d"}), "application/json"
            )
            assert status == 200

        add_prompt("Before")
        status, backup = http_call(port, "GET", "/api/data/backup", token)
        assert status == 200 and backup.startswith(b"SQLite format 3")
        add_prompt("After")
        assert sorted(prompts()) == ["After", "Before"]

        # Pad it past the 1 MB every ordinary request is held to, as a real backup would be.
        big = tmp_path / "big.db"
        big.write_bytes(backup)
        with closing(sqlite3.connect(big)) as conn:
            conn.execute("CREATE TABLE padding (data BLOB)")
            conn.execute("INSERT INTO padding VALUES (?)", (b"\x00" * (3 * 1024 * 1024),))
            conn.commit()
        upload = big.read_bytes()
        assert len(upload) > 1_000_000

        status, body = http_call(port, "POST", "/api/data/restore", token, upload, "application/octet-stream")
        assert status == 200, body
        assert "before-restore" in json.loads(body)["safety_copy"]
        assert prompts() == ["Before"]

        # A refused upload leaves the data alone, and the server answers the next request.
        status, body = http_call(port, "POST", "/api/data/restore", token, b"garbage" * 1000, "application/octet-stream")
        assert status == 400 and json.loads(body)["error"]
        assert prompts() == ["Before"]
        add_prompt("Still works")
        assert sorted(prompts()) == ["Before", "Still works"]
