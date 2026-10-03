"""Updating while the previous version is still running. It holds the lock, writes no
record of where it is, and never asks for a secret. A launch has to open it, not wait
out the full time and then say it is "not answering"."""

import pytest

import access
import app as app_module
from test_startup import TestCheckPort

OLDER = {"app": "lit-review"}  # what the previous version answers: no instance id
NEWER = {"app": "lit-review", "instance": "someone-elses-copy"}


@pytest.fixture
def clock(monkeypatch):
    """A clock the test controls: sleeping advances it, nothing really waits."""
    state = {"now": 1000.0}
    monkeypatch.setattr(app_module.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(app_module.time, "sleep", lambda seconds: state.__setitem__("now", state["now"] + seconds))
    return state


@pytest.fixture
def opened(monkeypatch, clock):
    """Records every browser opening: (port, token, time since the launch began)."""
    calls = []
    began = clock["now"]
    monkeypatch.setattr(app_module, "_open_browser", lambda port=None, token=None: calls.append((port, token, clock["now"] - began)))
    return calls


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


def answers_on_default_port(monkeypatch, reply):
    probed = []

    def probe(port):
        probed.append(port)
        return ("ours", reply) if port == app_module.PORT and reply is not None else (None, None)

    monkeypatch.setattr(app_module, "probe_port", probe)
    monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: None)
    return probed


class TestAnOlderCopy:
    def test_it_is_opened_as_it_is_once_the_grace_period_has_passed(self, state_dir, monkeypatch, opened, capsys):
        answers_on_default_port(monkeypatch, OLDER)

        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=15) == 0

        assert len(opened) == 1
        port, token, waited = opened[0]
        assert (port, token) == (app_module.PORT, None)  # the plain address: it asks for no secret
        assert app_module.LEGACY_GRACE_SECONDS <= waited < app_module.LEGACY_GRACE_SECONDS + 1
        out = capsys.readouterr().out
        assert "An older version of Lit Review is already running" in out
        assert f"http://127.0.0.1:{app_module.PORT}" in out
        assert "latest version" in out

    def test_it_is_not_opened_before_the_grace_period_is_up(self, state_dir, monkeypatch, opened):
        """A new copy that is merely still starting must not be mistaken for an older one."""
        answers_on_default_port(monkeypatch, OLDER)
        monkeypatch.setattr(app_module, "LEGACY_GRACE_SECONDS", 10)
        app_module.hand_over_to_running_copy(state_dir, wait_seconds=60)
        assert opened[0][2] >= 10

    def test_no_secret_is_made_or_read_for_an_older_copy(self, state_dir, monkeypatch, opened):
        answers_on_default_port(monkeypatch, OLDER)
        app_module.hand_over_to_running_copy(state_dir, wait_seconds=15)
        assert not (state_dir / access.TOKEN_FILE).exists()

    def test_only_the_default_port_is_looked_at(self, state_dir, monkeypatch, opened):
        probed = answers_on_default_port(monkeypatch, OLDER)
        app_module.hand_over_to_running_copy(state_dir, wait_seconds=15)
        assert set(probed) == {app_module.PORT}


class TestNotAnOlderCopy:
    def test_a_newer_copy_on_the_port_is_never_taken_for_one(self, state_dir, monkeypatch, opened, capsys):
        """It has an instance id, so it is a new-version copy (another user's, since this
        user's would have a record): it needs its owner's secret and is no use here."""
        answers_on_default_port(monkeypatch, NEWER)
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=15) == 1
        assert opened == []
        assert "not answering" in capsys.readouterr().err

    @pytest.mark.parametrize("reply", [None, {}, {"app": "something-else"}])
    def test_nothing_or_another_program_is_not_an_older_copy(self, state_dir, monkeypatch, opened, reply):
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: None)
        monkeypatch.setattr(app_module, "probe_port", lambda port: ("other", None) if reply == {} else (None, None))
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=15) == 1
        assert opened == []

    def test_an_empty_instance_id_still_counts_as_a_new_copy(self, state_dir, monkeypatch, opened):
        answers_on_default_port(monkeypatch, {"app": "lit-review", "instance": ""})
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=15) == 1
        assert opened == []

    def test_a_record_means_it_is_not_an_older_copy_even_if_it_is_slow(self, state_dir, monkeypatch, opened):
        """With a record the copy is a new one and is waited for by its id; the default
        port is never guessed at."""
        access.write_instance(state_dir, 5190, "mine")
        probed = answers_on_default_port(monkeypatch, OLDER)
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=15) == 1
        assert opened == []
        assert probed == []

    def test_a_record_that_appears_in_time_wins_over_guessing(self, state_dir, monkeypatch, opened, clock):
        answers_on_default_port(monkeypatch, OLDER)
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: "ours" if instance == "mine" else None)
        real_sleep = app_module.time.sleep

        def sleep(seconds):
            real_sleep(seconds)
            if clock["now"] >= 1000 + 2:  # the copy finishes starting and writes its record
                access.write_instance(state_dir, 5190, "mine")

        monkeypatch.setattr(app_module.time, "sleep", sleep)
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=15) == 0
        assert opened[0][0] == 5190 and opened[0][1]  # opened on that copy, signed in
        assert opened[0][2] < app_module.LEGACY_GRACE_SECONDS + 1


class TestProbePort:
    def serve(self, reply):
        from test_startup_hostile import Hostile

        return Hostile(lambda self, conn, req: conn.sendall(reply))

    def test_nothing_listening(self):
        from procutil import free_port

        assert app_module.probe_port(free_port()) == (None, None)

    def test_the_app_gives_its_reply(self):
        reply = TestCheckPort.http_reply('{"app": "lit-review", "instance": "abc"}')
        with self.serve(reply) as server:
            state, body = app_module.probe_port(server.port)
        assert state == "ours"
        assert body == {"app": "lit-review", "instance": "abc"}

    def test_an_older_copys_reply_has_no_instance(self):
        with self.serve(TestCheckPort.http_reply('{"app": "lit-review"}')) as server:
            state, body = app_module.probe_port(server.port)
        assert state == "ours" and "instance" not in body

    @pytest.mark.parametrize("reply", [b"junk", b"HTTP/1.1 404 Not Found\r\n\r\n", TestCheckPort.http_reply("[]")])
    def test_anything_else_is_other_with_no_reply(self, reply):
        with self.serve(reply) as server:
            assert app_module.probe_port(server.port) == ("other", None)

    def test_check_port_is_built_on_it_and_agrees(self):
        reply = TestCheckPort.http_reply('{"app": "lit-review", "instance": "abc"}')
        with self.serve(reply) as server:
            assert app_module.check_port(server.port) == "ours"
            assert app_module.check_port(server.port, instance="abc") == "ours"
            assert app_module.check_port(server.port, instance="other") == "other"
