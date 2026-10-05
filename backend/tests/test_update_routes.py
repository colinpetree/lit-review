"""The update routes: settings, "check now" and "install and restart"."""

import pytest

import app as app_module
import app_settings
import updater


@pytest.fixture(autouse=True)
def reset():
    updater.reset_for_tests()
    yield
    updater.reset_for_tests()
    app_module._GATE.open()
    app_module._QUIT["fn"] = None


class TestSettings:
    def test_default_is_off(self, client):
        assert client.get("/api/settings/updates").get_json() == {"auto_apply": False}

    def test_it_can_be_turned_on_and_off(self, client):
        assert client.put("/api/settings/updates", json={"auto_apply": True}).get_json() == {"auto_apply": True}
        assert app_settings.auto_apply() is True
        assert client.get("/api/settings/updates").get_json() == {"auto_apply": True}
        assert client.put("/api/settings/updates", json={"auto_apply": False}).get_json() == {"auto_apply": False}

    @pytest.mark.parametrize("body", [{}, {"auto_apply": "yes"}, {"auto_apply": 1}, {"auto_apply": None}, {"other": True}])
    def test_anything_but_true_or_false_is_refused_and_nothing_changes(self, client, body):
        assert client.put("/api/settings/updates", json=body).status_code == 400
        assert app_settings.auto_apply() is False

    def test_a_non_object_body_is_refused(self, client):
        assert client.put("/api/settings/updates", json=[True]).status_code == 400

    def test_the_status_reports_the_setting(self, client):
        client.put("/api/settings/updates", json={"auto_apply": True})
        assert client.get("/api/update-check").get_json()["auto_apply"] is True

    def test_a_page_from_another_site_cannot_change_it(self, client):
        response = client.put("/api/settings/updates", json={"auto_apply": True}, headers={"Origin": "https://evil.example"})
        assert response.status_code in (400, 403)
        assert app_settings.auto_apply() is False


class TestCheckNow:
    def test_starts_a_check_and_answers_at_once(self, client, monkeypatch):
        started = []
        monkeypatch.setattr(updater, "check_now", lambda jobs: started.append(jobs) or True)
        response = client.post("/api/update/check")
        assert response.status_code == 202 and response.get_json()["state"] == "idle"
        assert started == [app_module._jobs_running]


class TestApply:
    @pytest.fixture
    def ready(self, monkeypatch):
        calls = {"apply": 0, "quit": 0, "timers": []}
        monkeypatch.setattr(updater, "status", lambda: {"state": "staged"})

        def start_apply():
            calls["apply"] += 1

        monkeypatch.setattr(updater, "start_apply", start_apply)
        app_module._QUIT["fn"] = lambda: calls.__setitem__("quit", calls["quit"] + 1)

        class FakeTimer:
            def __init__(self, interval, function):
                calls["timers"].append((interval, function))

            def start(self):
                calls["timers"][-1][1]()

        monkeypatch.setattr(app_module.threading, "Timer", FakeTimer)
        return calls

    def test_nothing_staged_is_refused(self, client, ready, monkeypatch):
        monkeypatch.setattr(updater, "status", lambda: {"state": "available"})
        response = client.post("/api/update/apply")
        assert response.status_code == 409 and "no update" in response.get_json()["error"]
        assert ready["apply"] == 0

    def test_a_copy_that_cannot_restart_itself_is_refused(self, client, ready):
        app_module._QUIT["fn"] = None
        assert client.post("/api/update/apply").status_code == 409
        assert ready["apply"] == 0 and not app_module._GATE.closed

    def test_it_quiesces_starts_the_helper_and_quits_leaving_the_gate_closed(self, client, ready):
        response = client.post("/api/update/apply")
        assert response.status_code == 200 and response.get_json() == {"ok": True}
        assert ready["apply"] == 1 and ready["quit"] == 1
        assert app_module._GATE.closed  # every other request now gets a 503 while it restarts
        assert client.get("/api/about").status_code == 503

    def test_work_that_will_not_finish_changes_nothing(self, client, ready, monkeypatch):
        monkeypatch.setattr(app_module._GATE, "close_when_quiet", lambda timeout, own_requests=1: False)
        response = client.post("/api/update/apply")
        assert response.status_code == 409 and "still working" in response.get_json()["error"]
        assert ready["apply"] == 0 and ready["quit"] == 0

    def test_a_helper_that_cannot_start_reopens_the_gate_and_keeps_running(self, client, ready, monkeypatch):
        def fail():
            raise updater.UpdateError("denied")

        monkeypatch.setattr(updater, "start_apply", fail)
        response = client.post("/api/update/apply")
        assert response.status_code == 500 and "denied" in response.get_json()["error"]
        assert not app_module._GATE.closed and ready["quit"] == 0

    def test_a_second_click_while_one_is_running_is_refused(self, client, ready):
        with app_module._exclusive("update-apply", 0):
            assert client.post("/api/update/apply").status_code == 409
        assert ready["apply"] == 0

    def test_it_needs_the_session_like_every_other_call(self, client, ready):
        stranger = app_module.app.test_client()
        stranger.environ_base.pop("HTTP_AUTHORIZATION", None)
        response = stranger.post("/api/update/apply", base_url=f"http://127.0.0.1:{app_module.PORT}")
        assert response.status_code == 401 and ready["apply"] == 0
