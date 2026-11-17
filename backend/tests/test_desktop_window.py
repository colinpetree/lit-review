"""The app window (desktop_window.py) and what is wired to it: close hides, quit closes, a
second launch shows the running copy's window, and the browser takes over when the window
cannot be used. pywebview itself needs a desktop, so `DesktopShell` is driven with a
stand-in window here; the real window is checked by hand (RELEASING.md)."""

import json
import sys
import threading
import types

import pytest

import access
import app as app_module
import app_settings
import desktop_window
import tray
from desktop_window import DesktopShell


class FakeWindow:
    def __init__(self):
        self.calls = []

    def show(self):
        self.calls.append("show")

    def hide(self):
        self.calls.append("hide")

    def restore(self):
        self.calls.append("restore")

    def destroy(self):
        self.calls.append("destroy")


def run_now(target):
    target()


def make_shell(watchdog_seconds=0.05, **kwargs):
    opened, notices = [], []
    shell = DesktopShell(
        lambda: opened.append("browser"),
        first_hide=lambda: notices.append("notice"),
        start_thread=run_now,
        watchdog_seconds=watchdog_seconds,
        **kwargs,
    )
    window = FakeWindow()
    shell.attach(window)
    return shell, window, opened, notices


def loaded_shell():
    shell, window, opened, notices = make_shell(watchdog_seconds=5)
    shell.loaded.set()  # loaded before shown: the watchdog returns at once
    shell.on_shown()
    window.calls.clear()
    return shell, window, opened, notices


class TestShowing:
    def test_the_window_appears_once_the_page_has_loaded(self):
        shell, window, opened, _ = make_shell(watchdog_seconds=5)
        shell.shown.set()
        shell.on_loaded()
        assert window.calls == ["show"]
        shell.on_loaded()  # a later load (it never navigates, but if it did) does not show it again
        assert window.calls == ["show"] and not opened

    def test_a_show_before_the_window_exists_waits_for_it(self):
        shell, window, opened, _ = make_shell(watchdog_seconds=5)
        shell.show()  # a tray click while it is still starting
        assert window.calls == []
        shell.loaded.set()
        shell.on_shown()  # the watchdog sees the page loaded and does the remembered show
        assert window.calls == ["show"] and not opened

    def test_a_minimized_window_is_restored_as_well(self):
        shell, window, _, _ = loaded_shell()
        shell.on_minimized()
        shell.show()
        assert window.calls == ["restore", "show"]
        shell.on_restored()
        window.calls.clear()
        shell.show()
        assert window.calls == ["show"]

    def test_a_page_that_never_loads_means_the_browser(self):
        shell, window, opened, _ = make_shell(watchdog_seconds=0.01)
        shell.on_shown()
        assert opened == ["browser"] and shell.broken and not shell.has_window()
        shell.show()  # from now on the tray opens the browser
        assert opened == ["browser", "browser"] and window.calls == []
        shell.on_loaded()  # a page that loads after all does not pop up a second copy
        assert window.calls == []

    def test_a_window_call_that_fails_is_logged_not_raised(self, caplog):
        shell, window, _, _ = loaded_shell()

        def broken():
            raise RuntimeError("gone")

        window.show = broken
        shell.show()
        assert "A window call failed" in caplog.text


class TestClosing:
    def test_the_close_button_hides_and_the_first_time_says_so(self):
        shell, window, _, notices = loaded_shell()
        assert shell.on_closing() is False  # cancelled
        assert window.calls == ["hide"] and notices == ["notice"]
        assert shell.on_closing() is False
        assert window.calls == ["hide", "hide"] and notices == ["notice"]  # once

    def test_while_quitting_the_close_goes_ahead(self):
        shell, window, _, _ = loaded_shell()
        shell.quit()
        assert window.calls == ["destroy"]
        assert shell.on_closing() is None  # not cancelled
        assert window.calls == ["destroy"]

    def test_on_windows_the_form_decides_and_the_event_only_cancels(self):
        shell, window, _, notices = loaded_shell()
        shell.native_close = True
        assert shell.on_closing() is False
        assert window.calls == []  # pywebview's event no longer hides; the Form's handler does
        assert shell.on_native_closing(user_closing=True) is True
        assert window.calls == ["hide"] and notices == ["notice"]

    def test_signing_out_or_shutting_down_lets_the_window_close(self):
        shell, window, _, notices = loaded_shell()
        shell.native_close = True
        assert shell.on_native_closing(user_closing=False) is False  # not kept: Windows may end the session
        assert window.calls == [] and not notices
        # Another program may still cancel the sign-out, so nothing else changes: the close
        # button still hides afterwards.
        assert not shell.quitting and not shell.quit_requested.is_set()
        assert shell.on_native_closing(user_closing=True) is True and window.calls == ["hide"]

    def test_a_close_while_quitting_is_never_kept(self):
        shell, _, _, _ = loaded_shell()
        shell.native_close = True
        shell.quit()
        assert shell.on_native_closing(user_closing=True) is False


class TestQuitting:
    def test_quit_runs_the_stoppers_once_and_closes_the_window(self):
        shell, window, _, _ = loaded_shell()
        stopped = []
        shell.on_quit(lambda: stopped.append("tray"))
        shell.quit()
        shell.quit()  # main() calls it again after the loop ends
        assert stopped == ["tray"] and window.calls == ["destroy"]
        assert shell.quit_requested.is_set() and not shell.has_window()

    def test_after_windows_closed_it_quit_still_removes_the_tray_icon(self):
        shell, _, _, _ = loaded_shell()
        stopped = []
        shell.on_quit(lambda: stopped.append("tray"))
        shell.native_close = True
        shell.on_native_closing(user_closing=False)  # sign-out
        shell.quit()  # what main() does when the loop returns
        assert stopped == ["tray"]

    def test_a_quit_before_the_window_exists_closes_it_once_it_does(self):
        threads = []
        shell, window, _, _ = make_shell(watchdog_seconds=5)
        shell._start_thread = lambda target: threads.append(threading.Thread(target=target)) or threads[-1].start()
        shell.quit()  # the server died at once
        assert window.calls == []
        shell.shown.set()
        for thread in threads:
            thread.join(5)
        assert window.calls == ["destroy"]

    def test_a_failing_stopper_does_not_stop_the_rest(self, caplog):
        shell, window, _, _ = loaded_shell()

        def broken():
            raise RuntimeError("no icon")

        shell.on_quit(broken)
        shell.quit()
        assert window.calls == ["destroy"] and "Stopping part of the app failed" in caplog.text


class TestAvailable:
    def test_no_library_means_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "webview", None)  # import raises ImportError
        with pytest.raises(desktop_window.WindowUnavailable):
            desktop_window.available()

    @pytest.mark.parametrize("renderer", ["mshtml", "cef", None])
    def test_an_engine_that_cannot_run_the_page_is_unavailable(self, monkeypatch, renderer):
        """Without WebView2, pywebview quietly uses Internet Explorer, which cannot run the page."""
        fake_guilib = types.SimpleNamespace(initialize=lambda: types.SimpleNamespace(renderer=renderer))
        monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
        monkeypatch.setattr(desktop_window.importlib, "import_module", lambda name: fake_guilib)
        with pytest.raises(desktop_window.WindowUnavailable, match="WebView2"):
            desktop_window.available()

    @pytest.mark.parametrize("renderer", ["edgechromium", "wkwebview"])
    def test_the_system_engines_are_used(self, monkeypatch, renderer):
        fake = types.SimpleNamespace()
        fake_guilib = types.SimpleNamespace(initialize=lambda: types.SimpleNamespace(renderer=renderer))
        monkeypatch.setitem(sys.modules, "webview", fake)
        monkeypatch.setattr(desktop_window.importlib, "import_module", lambda name: fake_guilib)
        assert desktop_window.available() is fake


class TestWiring:
    def test_create_starts_hidden_and_connects_every_event(self):
        class Event(list):
            def __iadd__(self, handler):
                self.append(handler)
                return self

        made = {}

        def create_window(title, url, **options):
            made.update(title=title, url=url, **options)
            return types.SimpleNamespace(
                events=types.SimpleNamespace(**{name: Event() for name in ("shown", "loaded", "minimized", "restored", "closing")})
            )

        shell = DesktopShell(lambda: None)
        window = desktop_window.create(types.SimpleNamespace(create_window=create_window), "http://localhost:8100/#token=x", shell)
        assert made["hidden"] is True and made["url"] == "http://localhost:8100/#token=x"
        assert shell.window is window
        assert window.events.closing == [shell.on_closing] and window.events.loaded == [shell.on_loaded]
        assert window.events.shown == [shell.on_shown]

    def test_run_keeps_storage_turns_on_downloads_and_opens_links_outside(self, tmp_path):
        seen = {}
        fake = types.SimpleNamespace(settings={}, start=lambda func, **options: seen.update(options))
        desktop_window.run(fake, DesktopShell(lambda: None), tmp_path / "webview")
        assert seen == {"private_mode": False, "storage_path": str(tmp_path / "webview"), "debug": False}
        assert fake.settings["ALLOW_DOWNLOADS"] is True
        assert fake.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True

    @pytest.mark.parametrize(
        "names, kept",
        [
            (["copy", "-", "-", "paste"], ["copy", "-", "paste"]),
            (["-", "copy", "-"], ["copy"]),
            (["-", "-"], []),
            (["copy"], ["copy"]),
        ],
    )
    def test_separators_are_tidied(self, names, kept):
        class Items(list):
            Count = property(len)

            def RemoveAt(self, index):  # noqa: N802 - the .NET name
                del self[index]

        items = Items(types.SimpleNamespace(Kind="sep" if name == "-" else "cmd", Name=name) for name in names)
        desktop_window._tidy_separators(items, "sep")
        assert [item.Name for item in items] == kept


class TestWhenTheWindowIsUsed:
    @pytest.mark.parametrize(
        "argv, env, frozen, expected",
        [
            ([], {}, True, True),  # the packaged app
            ([], {}, False, False),  # from source: the browser
            (["--tray", "--window"], {}, False, True),
            (["--window"], {}, False, False),  # no tray, so no window (it could never come back)
            ([], {"LIT_REVIEW_NO_TRAY": "1"}, True, False),  # tests and CI
            ([], {"LIT_REVIEW_NO_WINDOW": "1"}, True, False),
            (["--no-window"], {}, True, False),
        ],
    )
    def test_window_wanted(self, monkeypatch, argv, env, frozen, expected):
        for name in ("LIT_REVIEW_NO_TRAY", "LIT_REVIEW_NO_WINDOW"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(app_module.bundle, "is_frozen", lambda: frozen)
        assert app_module._window_wanted(argv) is expected


@pytest.fixture
def anonymous(client):
    """The app's own address, no secret (as in test_auth.py)."""
    browser = app_module.app.test_client()
    browser.environ_base.pop("HTTP_AUTHORIZATION", None)
    return browser


@pytest.fixture
def window_shell(monkeypatch):
    shell, window, opened, _ = loaded_shell()
    monkeypatch.setitem(app_module._WINDOW, "shell", shell)
    return shell, window


class TestShowRoute:
    def test_it_shows_the_window(self, client, window_shell):
        shell, window = window_shell
        response = client.post("/api/window/show")
        assert response.status_code == 204 and window.calls == ["show"]

    def test_no_window_is_a_409_so_the_launch_opens_the_browser(self, client):
        assert client.post("/api/window/show").status_code == 409

    def test_a_window_that_never_loaded_is_a_409(self, client, window_shell):
        window_shell[0].broken = True
        assert client.post("/api/window/show").status_code == 409

    def test_it_needs_the_secret(self, anonymous, window_shell):
        assert anonymous.post("/api/window/show").status_code == 401
        assert window_shell[1].calls == []

    def test_a_website_cannot_ask(self, client, window_shell):
        response = client.post("/api/window/show", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403 and window_shell[1].calls == []

    def test_about_says_which_it_is(self, client, window_shell):
        assert client.get("/api/about").get_json()["shell"] == "window"
        app_module._WINDOW["shell"] = None
        assert client.get("/api/about").get_json()["shell"] == "browser"


class TestInstanceRecord:
    def test_a_copy_with_a_window_records_its_process(self, tmp_path):
        access.write_instance(tmp_path, 8101, "abc", window_pid=4242)
        assert access.read_instance(tmp_path) == {"port": 8101, "id": "abc", "window_pid": 4242}

    def test_without_a_window_the_record_is_as_before(self, tmp_path):
        access.write_instance(tmp_path, 8101, "abc")
        assert json.loads((tmp_path / access.INSTANCE_FILE).read_text(encoding="utf-8")) == {"port": 8101, "id": "abc"}
        assert access.read_instance(tmp_path) == {"port": 8101, "id": "abc"}

    @pytest.mark.parametrize("bad", ["12", True, 0, -3, 1.5, None])
    def test_a_bad_process_id_is_ignored(self, tmp_path, bad):
        (tmp_path / access.INSTANCE_FILE).write_text(json.dumps({"port": 8101, "id": "abc", "window_pid": bad}), encoding="utf-8")
        assert access.read_instance(tmp_path) == {"port": 8101, "id": "abc"}


class TestHandOver:
    @pytest.fixture
    def running(self, monkeypatch, tmp_path):
        """A running copy on record, answering as itself; records every browser opening."""
        opened, asked = [], []
        monkeypatch.setattr(app_module, "check_port", lambda port, instance=None: "ours")
        monkeypatch.setattr(app_module, "_open_browser", lambda port=None, token=None: opened.append(port))
        return tmp_path, opened, asked

    def test_a_copy_with_a_window_is_asked_to_show_it(self, running, monkeypatch):
        state_dir, opened, asked = running
        access.write_instance(state_dir, 8101, "abc", window_pid=4242)
        monkeypatch.setattr(app_module, "_ask_to_show_window", lambda record, token: asked.append(record) or True)
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=1) == 0
        assert asked[0]["window_pid"] == 4242 and opened == []

    def test_if_it_cannot_the_browser_is_opened(self, running, monkeypatch):
        state_dir, opened, asked = running
        access.write_instance(state_dir, 8101, "abc", window_pid=4242)
        monkeypatch.setattr(app_module, "_ask_to_show_window", lambda record, token: asked.append(record) and False)
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=1) == 0
        assert len(asked) == 1 and opened == [8101]

    def test_a_copy_without_a_window_is_not_asked(self, running, monkeypatch):
        state_dir, opened, _ = running
        access.write_instance(state_dir, 8101, "abc")
        monkeypatch.setattr(app_module, "_ask_to_show_window", lambda record, token: pytest.fail("no window to ask about"))
        assert app_module.hand_over_to_running_copy(state_dir, wait_seconds=1) == 0
        assert opened == [8101]

    def test_the_request_carries_the_secret_and_needs_a_204(self, monkeypatch):
        sent = {}

        class Connection:
            def __init__(self, host, port, timeout):
                sent.update(host=host, port=port, timeout=timeout)

            def request(self, method, path, headers):
                sent.update(method=method, path=path, headers=headers)

            def getresponse(self):
                return types.SimpleNamespace(status=sent.get("status", 204))

            def close(self):
                sent["closed"] = True

        import http.client

        monkeypatch.setattr(http.client, "HTTPConnection", Connection)
        monkeypatch.setattr(app_module, "_allow_foreground", lambda pid: sent.update(pid=pid))
        record = {"port": 8101, "id": "abc", "window_pid": 4242}
        assert app_module._ask_to_show_window(record, "secret") is True
        assert sent["host"] == "127.0.0.1" and sent["port"] == 8101 and sent["pid"] == 4242
        assert (sent["method"], sent["path"]) == ("POST", "/api/window/show")
        assert sent["headers"]["Authorization"] == "Bearer secret" and sent["closed"]
        sent["status"] = 409
        assert app_module._ask_to_show_window(record, "secret") is False

    def test_no_answer_is_false(self, monkeypatch):
        monkeypatch.setattr(app_module, "_allow_foreground", lambda pid: None)
        port = _closed_port()
        assert app_module._ask_to_show_window({"port": port, "id": "x", "window_pid": 1}, "s") is False


def _closed_port():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestFirstHideNotice:
    def test_shown_once_per_install_and_only_on_windows(self, monkeypatch):
        notes = []
        icon = types.SimpleNamespace(notify=lambda title, message: notes.append(title))
        monkeypatch.setattr(app_module.sys, "platform", "win32")
        app_module._first_hide_notice({"icon": icon})
        app_module._first_hide_notice({"icon": icon})
        assert notes == [desktop_window.FIRST_HIDE_TITLE]
        assert app_settings.load()["tray_notice_shown"] is True

    def test_not_on_a_mac(self, monkeypatch):
        monkeypatch.setattr(app_module.sys, "platform", "darwin")
        icon = types.SimpleNamespace(notify=lambda title, message: pytest.fail("the Dock icon says so already"))
        app_module._first_hide_notice({"icon": icon})


class FakeIcon:
    instances = []
    HAS_NOTIFICATION = True

    def __init__(self, name, image, title, menu):
        self.menu = menu
        self.visible = False
        self.stopped = False
        self.ran = False
        self.notes = []
        FakeIcon.instances.append(self)

    def run(self, setup=None):
        self.ran = True
        if setup:
            setup(self)

    def stop(self):
        self.stopped = True

    def notify(self, message, title):
        self.notes.append((title, message))


class TestTrayForTheWindow:
    @pytest.fixture
    def fake_pystray(self, monkeypatch):
        FakeIcon.instances.clear()
        module = types.SimpleNamespace(
            Icon=FakeIcon,
            Menu=lambda *items: list(items),
            MenuItem=lambda text, action, default=False: (text, action, default),
        )
        monkeypatch.setitem(sys.modules, "pystray", module)
        return module

    def test_the_menu_has_open_in_browser_and_quit_ends_the_app(self, fake_pystray, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        events = []
        icon = tray.Tray(
            lambda: events.append("show"),
            lambda: events.append("logs"),
            lambda: True,
            open_browser=lambda: events.append("browser"),
            stop_app=lambda: events.append("quit"),
        )
        icon.start()
        fake = FakeIcon.instances[0]
        for thread in threading.enumerate():
            if thread.name == "tray":
                thread.join(5)
        assert fake.ran and fake.visible
        assert [item[0] for item in fake.menu] == ["Open Lit Review", "Open in browser", "Open log folder", "Quit"]
        assert fake.menu[0][2] is True  # a click on the icon shows the window
        for item in fake.menu:
            item[1](fake, item)
        assert events == ["show", "browser", "logs", "quit"]
        assert not fake.stopped  # Quit ends the app (which stops the icon), not just the icon

    def test_stop_removes_the_icon_on_windows(self, fake_pystray, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        icon = tray.Tray(lambda: None, lambda: None, lambda: True)
        icon.start()
        icon.stop()
        assert FakeIcon.instances[0].stopped

    def test_on_a_mac_stop_leaves_the_shared_loop_alone(self, fake_pystray, monkeypatch):
        """pystray's stop() would stop NSApplication, which runs the window too."""
        monkeypatch.setattr(tray.sys, "platform", "darwin")
        monkeypatch.setattr(tray.mac_app, "MacActions", lambda *args: types.SimpleNamespace())
        FakeIcon.run_detached = lambda self, setup=None: setup and setup(self)
        try:
            icon = tray.Tray(lambda: None, lambda: None, lambda: True)
            icon.start()
            icon.stop()
            assert not FakeIcon.instances[0].stopped
        finally:
            del FakeIcon.run_detached

    def test_notify_never_raises(self, fake_pystray, monkeypatch, caplog):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        icon = tray.Tray(lambda: None, lambda: None, lambda: True)
        icon.notify("t", "m")  # before start: nothing to notify from
        icon.start()
        icon.notify("Title", "Message")
        assert FakeIcon.instances[0].notes == [("Title", "Message")]

        def broken(message, title):
            raise OSError("no shell")

        FakeIcon.instances[0].notify = broken
        icon.notify("Title", "Message")
        assert "Could not show a tray notification" in caplog.text


class TestSelfCheckOfTheWindow:
    """The updater runs a new version's self-check on the user's computer and refuses it if it
    fails, so the window's check must look for files and modules only, never load .NET or AppKit's
    application object (which can fail on one computer while the app works there in the browser)."""

    def test_it_passes_from_source_and_loads_nothing_from_the_computer(self):
        import subprocess
        from pathlib import Path

        script = (
            "import sys, selfcheck; selfcheck._check_window(); "
            "print(sorted(m for m in ('clr', 'System', 'webview.platforms.winforms', "
            "'webview.platforms.edgechromium', 'webview.platforms.cocoa', 'AppKit') if m in sys.modules))"
        )
        done = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(app_module.__file__).parent, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() == "[]"

    def test_a_module_missing_from_the_build_fails_it(self, monkeypatch):
        import selfcheck

        monkeypatch.setitem(selfcheck.WINDOW_MODULES, sys.platform, ["no_such_module_in_this_build"])
        with pytest.raises(ModuleNotFoundError, match="no_such_module_in_this_build"):
            selfcheck._check_window()

    @pytest.mark.skipif(sys.platform != "win32", reason="the window's files are checked on Windows")
    def test_a_file_missing_from_the_build_fails_it(self, monkeypatch):
        import selfcheck

        monkeypatch.setattr(selfcheck, "WINDOW_FILES_WINDOWS", [("webview", "lib", "Missing.dll")])
        with pytest.raises(FileNotFoundError, match="Missing.dll"):
            selfcheck._check_window()


class TestServeWithWindowWithoutATray:
    def test_a_tray_icon_that_cannot_start_means_the_browser_and_no_window(self, monkeypatch, tmp_path):
        class Icon:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise tray.TrayUnavailable("no notification area")

        served, timers = [], []

        class Server:
            def serve_forever(self):
                served.append(True)

            def shutdown(self):
                pass

        class FakeTimer:
            def __init__(self, interval, function, args=()):
                timers.append(function)

            def start(self):
                pass

        monkeypatch.setattr(tray, "Tray", Icon)
        monkeypatch.setattr(app_module, "Timer", FakeTimer)
        monkeypatch.setattr(desktop_window, "create", lambda *a: pytest.fail("no window without a tray"))
        monkeypatch.setattr(desktop_window, "run", lambda *a, **k: pytest.fail("no window without a tray"))
        monkeypatch.setitem(app_module._QUIT, "fn", None)
        app_module._serve_with_window(Server(), object(), 8100, "secret", tmp_path, tmp_path / "logs")
        assert served and len(timers) == 1  # the browser is opened, and the app is served
        assert app_module._QUIT["fn"] is not None and app_module._WINDOW["shell"] is None


class TestSourceRunIcon:
    def test_the_packaged_app_passes_none(self, monkeypatch):
        """Its icon comes from the .exe or the .app bundle; on a Mac one passed here would replace it."""
        monkeypatch.setattr(app_module.bundle, "is_frozen", lambda: True)
        assert app_module._source_run_icon() is None

    @pytest.mark.parametrize("platform, name", [("win32", "LitReview.ico"), ("darwin", "icon-source.png")])
    def test_from_source_the_app_icon_is_used_when_it_exists(self, monkeypatch, tmp_path, platform, name):
        # A real folder: macOS and Linux follow "backend/.." through the folder itself, so a path
        # through one that does not exist is not found (Windows works it out from the text).
        backend = tmp_path / "backend"
        backend.mkdir()
        monkeypatch.setattr(app_module.bundle, "is_frozen", lambda: False)
        monkeypatch.setattr(app_module.bundle, "resource_path", lambda *parts: backend.joinpath(*parts))
        monkeypatch.setattr(app_module.sys, "platform", platform)
        assert app_module._source_run_icon() is None  # not made yet: pywebview's default
        icon = tmp_path / "packaging" / ("build" if platform == "win32" else "") / name
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes(b"x")
        assert app_module._source_run_icon().resolve() == icon.resolve()

    def test_run_passes_the_icon_only_when_there_is_one(self, tmp_path):
        seen = {}
        fake = types.SimpleNamespace(settings={}, start=lambda func, **options: seen.update(options))
        desktop_window.run(fake, DesktopShell(lambda: None), tmp_path, icon=tmp_path / "LitReview.ico")
        assert seen["icon"] == str(tmp_path / "LitReview.ico")
        seen.clear()
        desktop_window.run(fake, DesktopShell(lambda: None), tmp_path)
        assert "icon" not in seen
