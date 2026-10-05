"""The decisions startup makes, tested in one process: finding a port (including
when two copies look at the same moment), every early exit of main(), and how a
second launch finds and waits for the first."""

import socket
import sqlite3
import threading

import pytest

import access
import app as app_module
import db
import single_instance
from app import PortTaken, SingleOwnerServer
from procutil import free_port, free_port_run
from test_startup import TestCheckPort

GENUINE = TestCheckPort.http_reply('{"app": "lit-review", "instance": "abc"}')


class Listener:
    """Something that holds a port: hangs up on every connection."""

    def __init__(self, port, listen=True):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", port))
        self.stop = threading.Event()
        self.thread = None
        if listen:
            self.sock.listen(5)
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _run(self):
        self.sock.settimeout(0.1)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
                conn.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop.set()
        if self.thread:
            self.thread.join(5)
        self.sock.close()


@pytest.fixture
def run_of_ports():
    return free_port_run(6)


def closed(server):
    server.server_close()
    return server.server_address[1]


class TestStartServer:
    def test_the_first_free_port_is_taken(self, run_of_ports):
        server = app_module.start_server(start=run_of_ports, count=6)
        try:
            assert server.server_port == run_of_ports
            assert isinstance(server, SingleOwnerServer)
        finally:
            server.server_close()

    def test_a_port_with_something_listening_is_stepped_over(self, run_of_ports):
        with Listener(run_of_ports):
            server = app_module.start_server(start=run_of_ports, count=6)
            try:
                assert server.server_port == run_of_ports + 1
            finally:
                server.server_close()

    def test_several_taken_ports_in_a_row_are_all_stepped_over(self, run_of_ports):
        with Listener(run_of_ports), Listener(run_of_ports + 1), Listener(run_of_ports + 2):
            server = app_module.start_server(start=run_of_ports, count=6)
            try:
                assert server.server_port == run_of_ports + 3
            finally:
                server.server_close()

    def test_another_users_copy_of_the_app_is_stepped_over(self, run_of_ports, monkeypatch):
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", {f"127.0.0.1:{run_of_ports}"})
        other = SingleOwnerServer("127.0.0.1", run_of_ports, app_module.app)
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            assert app_module.check_port(run_of_ports) == "ours"  # it is a copy of this app...
            server = app_module.start_server(start=run_of_ports, count=6)
            try:
                assert server.server_port == run_of_ports + 1  # ...and of no use to this user
            finally:
                server.server_close()
        finally:
            other.shutdown()
            other.server_close()
            thread.join(5)

    def test_a_port_held_by_something_that_never_accepts_is_stepped_over_too(self, run_of_ports):
        with Listener(run_of_ports, listen=False):  # bound, not listening: nothing to connect to
            assert app_module.check_port(run_of_ports) is None  # the port check cannot see it...
            server = app_module.start_server(start=run_of_ports, count=6)  # ...the bind can
            try:
                assert server.server_port == run_of_ports + 1
            finally:
                server.server_close()

    def test_losing_the_race_to_another_copy_means_trying_the_next_port(self, run_of_ports, monkeypatch):
        """Two copies look at the same moment, both see the first port free, one binds it."""
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: None)  # "free", wrongly
        with Listener(run_of_ports):  # the other copy got there between the look and the bind
            server = app_module.start_server(start=run_of_ports, count=6)
            try:
                assert server.server_port == run_of_ports + 1
            finally:
                server.server_close()

    def test_when_every_port_is_taken_it_says_so_with_none(self, run_of_ports):
        with Listener(run_of_ports), Listener(run_of_ports + 1), Listener(run_of_ports + 2):
            assert app_module.start_server(start=run_of_ports, count=3) is None

    def test_it_never_goes_past_the_count_it_was_given(self, run_of_ports):
        with Listener(run_of_ports):
            assert app_module.start_server(start=run_of_ports, count=1) is None
            server = app_module.start_server(start=run_of_ports, count=2)
            try:
                assert server.server_port == run_of_ports + 1
            finally:
                server.server_close()

    def test_the_default_start_is_the_default_port(self, monkeypatch, run_of_ports):
        monkeypatch.setattr(app_module, "PORT", run_of_ports)
        server = app_module.start_server()
        try:
            assert server.server_port == run_of_ports
        finally:
            server.server_close()

    def test_refused_ports_leave_no_sockets_behind(self, run_of_ports, monkeypatch):
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: None)
        with Listener(run_of_ports), Listener(run_of_ports + 1):
            server = app_module.start_server(start=run_of_ports, count=6)
            server.server_close()
        # nothing of ours is still holding the two ports that were refused
        for port in (run_of_ports, run_of_ports + 1):
            probe = socket.socket()
            probe.bind(("127.0.0.1", port))
            probe.close()

    @pytest.mark.parametrize("round_number", range(8))
    def test_two_copies_looking_at_the_same_moment_end_up_on_different_ports(self, round_number):
        """The real race, run for real: both threads start together, neither can see the
        other's port yet, and each must still end up with its own."""
        start = free_port_run(6)
        barrier = threading.Barrier(2)
        results, errors = [], []

        def claim():
            try:
                barrier.wait(5)
                results.append(app_module.start_server(start=start, count=6))
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        try:
            assert errors == []
            assert len(results) == 2 and all(r is not None for r in results)
            assert results[0].server_port != results[1].server_port
            assert {r.server_port for r in results} <= set(range(start, start + 6))
        finally:
            for r in results:
                if r is not None:
                    r.server_close()


class TestCheckPortKnowsWhichCopy:
    def serve_reply(self, reply):
        from test_startup_hostile import Hostile

        return Hostile(lambda self, conn, req: conn.sendall(reply))

    def test_the_copy_with_the_expected_id_is_ours(self):
        with self.serve_reply(GENUINE) as server:
            assert app_module.check_port(server.port, instance="abc") == "ours"

    def test_another_copy_on_the_same_port_is_not(self):
        with self.serve_reply(GENUINE) as server:
            assert app_module.check_port(server.port, instance="someone-elses") == "other"

    def test_a_reply_with_no_id_is_not_a_particular_copy(self):
        reply = TestCheckPort.http_reply('{"app": "lit-review"}')
        with self.serve_reply(reply) as server:
            assert app_module.check_port(server.port, instance="abc") == "other"
            assert app_module.check_port(server.port) == "ours"  # fine when no particular copy is asked for

    def test_without_an_expected_id_any_copy_counts(self):
        with self.serve_reply(GENUINE) as server:
            assert app_module.check_port(server.port) == "ours"
            assert app_module.check_port(server.port, instance=None) == "ours"

    @pytest.mark.parametrize("instance_value", ["null", "7", '["abc"]', '""', "{}"])
    def test_an_odd_id_in_the_reply_is_not_a_match(self, instance_value):
        reply = TestCheckPort.http_reply('{"app": "lit-review", "instance": %s}' % instance_value)
        with self.serve_reply(reply) as server:
            assert app_module.check_port(server.port, instance="abc") == "other"

    def test_the_health_reply_is_returned_as_a_dict(self):
        assert app_module._health_reply(GENUINE)["instance"] == "abc"
        assert app_module._health_reply(b"junk") is None


class TestHandOver:
    @pytest.fixture(autouse=True)
    def quiet(self, monkeypatch):
        monkeypatch.setenv("LIT_REVIEW_NO_BROWSER", "1")
        monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)
        # Nothing answers on the default port unless a test says so.
        monkeypatch.setattr(app_module, "probe_port", lambda port: (None, None))

    @pytest.fixture
    def state_dir(self, tmp_path):
        return tmp_path / "state"

    def test_it_opens_the_signed_in_browser_on_the_copy_the_record_names(self, state_dir, monkeypatch, capsys):
        access.write_instance(state_dir, 5188, "id-1")
        token = access.load_or_create_token(state_dir)
        calls = []
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: calls.append((port, instance)) or "ours")

        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=5) == 0

        out = capsys.readouterr().out
        assert "already running" in out
        assert f"Would open http://localhost:5188/#token={token}" in out
        assert calls == [(5188, "id-1")]  # asked about that copy specifically, not the default port

    def test_it_never_uses_the_default_port_when_the_record_says_another(self, state_dir, monkeypatch, capsys):
        access.write_instance(state_dir, app_module.PORT + 7, "id-1")
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: "ours")
        app_module.hand_over_to_running_copy(state_dir, wait_seconds=5)
        assert f"localhost:{app_module.PORT + 7}/#token=" in capsys.readouterr().out

    def test_it_waits_for_a_copy_that_has_not_written_its_record_yet(self, state_dir, monkeypatch, capsys):
        records = iter([None, None, None])
        monkeypatch.setattr(app_module.access, "read_instance", lambda d: next(records, {"port": 5190, "id": "late"}))
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: "ours")
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=60) == 0
        assert "localhost:5190/#token=" in capsys.readouterr().out

    def test_it_waits_for_a_copy_that_has_a_record_but_is_not_answering_yet(self, state_dir, monkeypatch, capsys):
        access.write_instance(state_dir, 5188, "id-1")
        answers = iter([None, None, "other", "ours"])
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: next(answers))
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=60) == 0
        assert "Would open" in capsys.readouterr().out

    def test_a_record_of_a_copy_that_is_gone_is_never_opened(self, state_dir, monkeypatch, capsys):
        access.write_instance(state_dir, 5188, "stale")
        clock = iter(range(0, 1000))
        monkeypatch.setattr(app_module.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: None)
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=4) == 1
        captured = capsys.readouterr()
        assert "not answering" in captured.err
        assert "Would open" not in captured.out

    def test_another_users_copy_on_that_port_is_never_opened(self, state_dir, monkeypatch, capsys):
        access.write_instance(state_dir, 5188, "mine")
        clock = iter(range(0, 1000))
        monkeypatch.setattr(app_module.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: "ours" if instance is None else "other")
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=4) == 1
        assert "Would open" not in capsys.readouterr().out

    def test_with_no_record_at_all_it_gives_up_after_the_wait(self, state_dir, monkeypatch, capsys):
        clock = iter(range(0, 1000))
        monkeypatch.setattr(app_module.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: pytest.fail("nothing to ask about"))
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=3) == 1
        assert "not answering" in capsys.readouterr().err


@pytest.fixture
def state_dir():
    return db.DB_PATH.parent


@pytest.fixture
def fake_server(monkeypatch):
    """Stands in for the real server, so main() can be run to the end in-process."""

    class Fake:
        def __init__(self):
            self.server_port = free_port()
            self.closed = False
            self.seen = {}
            self.raise_on_serve = None

        def serve_forever(self):
            self.seen["token"] = app_module.app.config["ACCESS_TOKEN"]
            self.seen["hosts"] = set(app_module.ALLOWED_HOSTS)
            self.seen["record"] = access.read_instance(db.DB_PATH.parent)
            if self.raise_on_serve:
                raise self.raise_on_serve
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True

    fake = Fake()
    monkeypatch.setattr(app_module, "start_server", lambda *a, **k: fake)
    monkeypatch.setattr(app_module, "ALLOWED_HOSTS", set(app_module.ALLOWED_HOSTS))
    timers = []

    class FakeTimer:
        def __init__(self, interval, function, args=()):
            timers.append((interval, function, args))

        def start(self):
            pass

    monkeypatch.setattr(app_module, "Timer", FakeTimer)
    fake.timers = timers
    return fake


class TestMain:
    def test_a_normal_start_serves_with_the_secret_set_and_cleans_up_after(self, state_dir, fake_server, capsys):
        assert app_module.main() == 0

        token = (state_dir / access.TOKEN_FILE).read_text(encoding="utf-8").strip()
        port = fake_server.server_port
        assert fake_server.seen["token"] == token  # the secret was in place before serving began
        assert {f"127.0.0.1:{port}", f"localhost:{port}"} <= fake_server.seen["hosts"]
        assert fake_server.seen["record"] == {"port": port, "id": app_module.INSTANCE_ID}
        assert fake_server.closed
        assert access.read_instance(state_dir) is None  # its record is removed on the way out
        single_instance.acquire(state_dir / "instance.lock").release()  # and the lock is free again
        out = capsys.readouterr().out
        assert f"Lit Review is running at http://localhost:{port}" in out
        assert f"http://localhost:{port}/#token={token}" in out  # the private link, if no browser opens

    def test_the_browser_is_asked_to_open_the_signed_in_link(self, state_dir, fake_server):
        app_module.main()
        interval, function, args = fake_server.timers[0]
        assert function is app_module._open_browser
        token = (state_dir / access.TOKEN_FILE).read_text(encoding="utf-8").strip()
        assert args == (fake_server.server_port, token)
        assert interval == 1

    def test_the_secret_is_kept_between_runs(self, state_dir, fake_server):
        app_module.main()
        first = (state_dir / access.TOKEN_FILE).read_text(encoding="utf-8")
        app_module.main()
        assert (state_dir / access.TOKEN_FILE).read_text(encoding="utf-8") == first

    def test_it_cleans_up_even_if_serving_fails(self, state_dir, fake_server):
        fake_server.raise_on_serve = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            app_module.main()
        assert fake_server.closed
        assert access.read_instance(state_dir) is None
        single_instance.acquire(state_dir / "instance.lock").release()

    def test_another_copy_of_this_user_means_hand_over_not_start(self, state_dir, fake_server, monkeypatch):
        holder = single_instance.acquire(state_dir / "instance.lock")
        monkeypatch.setattr(app_module, "hand_over_to_running_copy", lambda d: ("handed over", d))
        try:
            assert app_module.main() == ("handed over", state_dir)
        finally:
            holder.release()
        assert fake_server.seen == {}  # it never started a server

    def test_no_free_port_is_explained(self, state_dir, monkeypatch, capsys):
        monkeypatch.setattr(app_module, "start_server", lambda *a, **k: None)
        assert app_module.main() == 1
        err = capsys.readouterr().err
        assert "could not find a free port" in err
        assert str(app_module.PORT) in err and str(app_module.PORT + app_module.PORT_FALLBACK_COUNT - 1) in err
        single_instance.acquire(state_dir / "instance.lock").release()

    def test_a_normal_start_gives_no_warning(self, state_dir, fake_server, capsys):
        app_module.main()
        assert "Warning" not in capsys.readouterr().err


class TestUpdateHooks:
    """How main() uses the updater: apply a due update before serving, report the start, wait for the old copy."""

    def test_a_due_update_is_handed_to_the_helper_before_anything_is_served(self, state_dir, fake_server, monkeypatch):
        monkeypatch.setattr(app_module.updater, "apply_at_launch", lambda: True)
        assert app_module.main() == 0
        assert fake_server.seen == {}  # no server, no instance record, no browser
        assert access.read_instance(state_dir) is None
        assert fake_server.timers == []
        single_instance.acquire(state_dir / "instance.lock").release()  # the lock was let go for the new copy

    def test_no_update_due_serves_as_usual(self, state_dir, fake_server, monkeypatch):
        monkeypatch.setattr(app_module.updater, "apply_at_launch", lambda: False)
        assert app_module.main() == 0
        assert fake_server.seen["token"]

    def test_the_marker_result_and_cleanup_run_once_the_app_is_up(self, state_dir, fake_server, monkeypatch):
        order = []
        monkeypatch.setattr(app_module.updater, "write_started_marker", lambda: order.append("marker"))
        monkeypatch.setattr(app_module.updater, "take_result", lambda: order.append("result") or "It failed.")
        monkeypatch.setattr(app_module.updater, "note_failure", lambda message: order.append(("note", message)))
        monkeypatch.setattr(app_module.updater, "cleanup_stale", lambda: order.append("cleanup"))
        monkeypatch.setattr(app_module.updater, "start_background", lambda jobs: order.append("thread"))
        app_module.main()
        # The marker comes first: a waiting helper rolls back without it, and cleanup must not run before it.
        assert order == ["marker", "result", ("note", "It failed."), "cleanup", "thread"]

    def test_the_marker_is_not_written_if_the_instance_record_could_not_be(self, state_dir, fake_server, monkeypatch):
        written = []
        monkeypatch.setattr(app_module.updater, "write_started_marker", lambda: written.append(1))

        def fail(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(access, "write_instance", fail)
        monkeypatch.setattr(app_module, "_data_folder_problem", lambda *args: 1)
        assert app_module.main() == 1
        assert written == []

    def test_the_checking_thread_is_stopped_on_the_way_out(self, state_dir, fake_server, monkeypatch):
        stopped = []
        monkeypatch.setattr(app_module.updater, "stop_background", lambda: stopped.append(1))
        app_module.main()
        assert stopped == [1]

    def test_a_copy_started_by_the_helper_waits_for_the_old_one_to_let_go(self, state_dir):
        held, let_go = threading.Event(), threading.Event()

        def old_copy():
            # Taken and released on one thread: filelock locks belong to the thread that took them.
            holder = single_instance.acquire(state_dir / "instance.lock")
            held.set()
            let_go.wait(5)
            holder.release()

        thread = threading.Thread(target=old_copy)
        thread.start()
        assert held.wait(5)
        threading.Timer(0.6, let_go.set).start()
        lock = app_module._acquire_instance_lock(state_dir, after_update=True)
        lock.release()
        thread.join(5)

    def test_an_ordinary_launch_does_not_wait(self, state_dir):
        holder = single_instance.acquire(state_dir / "instance.lock")
        try:
            with pytest.raises(single_instance.AlreadyRunning):
                app_module._acquire_instance_lock(state_dir, after_update=False)
        finally:
            holder.release()

    def test_a_helper_started_copy_gives_up_after_the_wait_and_hands_over(self, state_dir, monkeypatch):
        holder = single_instance.acquire(state_dir / "instance.lock")
        clock = iter([0, 5, 31, 31])
        monkeypatch.setattr(app_module.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)
        try:
            with pytest.raises(single_instance.AlreadyRunning):
                app_module._acquire_instance_lock(state_dir, after_update=True)
        finally:
            holder.release()


class TestAnUnusableDataFolder:
    def friendly(self, capsys, folder, reason):
        err = capsys.readouterr().err
        assert "Lit Review cannot use its data folder" in err
        assert str(folder) in err
        assert reason in err
        assert "Make sure that folder can be written to and the disk is not full" in err
        assert "Traceback" not in err

    @pytest.mark.parametrize(
        "error, reason",
        [
            (PermissionError(13, "Access is denied"), "Access is denied"),
            (NotADirectoryError(20, "The directory name is invalid"), "The directory name is invalid"),
            (FileExistsError(17, "Cannot create a file when that file already exists"), "Cannot create a file"),
            (OSError(28, "There is not enough space on the disk"), "not enough space"),
        ],
    )
    def test_the_lock_file_cannot_be_made(self, state_dir, monkeypatch, capsys, error, reason):
        def broken(path):
            raise error

        monkeypatch.setattr(single_instance, "acquire", broken)
        assert app_module.main() == 1
        self.friendly(capsys, state_dir, reason)

    def test_the_database_cannot_be_opened(self, state_dir, monkeypatch, capsys):
        def broken():
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr(db, "ensure_ready", broken)
        assert app_module.main() == 1
        self.friendly(capsys, state_dir, "unable to open database file")
        single_instance.acquire(state_dir / "instance.lock").release()  # the lock is not left held

    def test_the_database_is_damaged(self, state_dir, monkeypatch, capsys):
        monkeypatch.setattr(db, "ensure_ready", lambda: (_ for _ in ()).throw(sqlite3.DatabaseError("file is not a database")))
        assert app_module.main() == 1
        self.friendly(capsys, state_dir, "file is not a database")

    def test_the_secret_file_cannot_be_written(self, state_dir, monkeypatch, capsys):
        def broken(directory):
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(access, "load_or_create_token", broken)
        assert app_module.main() == 1
        self.friendly(capsys, state_dir, "Access is denied")

    def test_the_record_cannot_be_written_after_the_server_is_up_and_the_port_is_released(self, state_dir, monkeypatch, capsys):
        port = free_port()
        real = SingleOwnerServer("127.0.0.1", port, app_module.app)
        monkeypatch.setattr(app_module, "start_server", lambda *a, **k: real)
        monkeypatch.setattr(app_module, "ALLOWED_HOSTS", set())

        def broken(directory, p, i):
            raise OSError(28, "There is not enough space on the disk")

        monkeypatch.setattr(access, "write_instance", broken)
        assert app_module.main() == 1
        self.friendly(capsys, state_dir, "not enough space")
        probe = socket.socket()
        probe.bind(("127.0.0.1", port))  # the port was given back
        probe.close()

    def test_the_message_names_the_real_reason_for_each_kind_of_error(self, tmp_path, capsys):
        app_module._data_folder_problem(tmp_path, PermissionError(13, "Access is denied"))
        assert "Access is denied" in capsys.readouterr().err
        app_module._data_folder_problem(tmp_path, sqlite3.OperationalError("disk I/O error"))
        assert "disk I/O error" in capsys.readouterr().err
        app_module._data_folder_problem(tmp_path, RuntimeError())
        assert "cannot use its data folder" in capsys.readouterr().err

    def test_the_message_goes_to_stderr_and_nothing_is_printed_as_running(self, state_dir, monkeypatch, capsys):
        monkeypatch.setattr(single_instance, "acquire", lambda p: (_ for _ in ()).throw(PermissionError(13, "Access is denied")))
        app_module.main()
        captured = capsys.readouterr()
        assert "is running at" not in captured.out
        assert captured.out == ""
