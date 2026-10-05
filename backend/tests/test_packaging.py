"""What the packaged (windowed, tray) build needs: finding its own files, telling the
user things with no console, a log file that never holds a secret, and the tray."""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import app as app_module
import bundle
import llm
import logfile
import selfcheck
import tray
import ui
import version


class TestBundle:
    def test_from_source_files_are_beside_the_code(self):
        assert not bundle.is_frozen()
        assert bundle.resource_path("static") == app_module.Path(bundle.__file__).resolve().parent / "static"

    def test_a_frozen_app_looks_where_pyinstaller_unpacked_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert bundle.is_frozen()
        assert bundle.resource_path("static", "index.html") == tmp_path / "static" / "index.html"

    def test_the_app_serves_from_that_folder(self):
        assert app_module.STATIC_DIR == bundle.resource_path("static")


class TestUi:
    @pytest.fixture
    def windowed(self, monkeypatch):
        """A packaged build: nothing to print to."""
        monkeypatch.setattr(ui, "_HAS_CONSOLE", False)
        monkeypatch.delenv("LIT_REVIEW_NO_DIALOG", raising=False)

    def test_an_error_goes_to_the_console_when_there_is_one(self, capsys):
        ui.show_error("Lit Review", "It broke.")
        assert "It broke." in capsys.readouterr().err

    def test_with_no_console_an_error_is_a_dialog(self, windowed, monkeypatch):
        shown = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(ui, "_mac_dialog", lambda *args: shown.append(args))
        ui.show_error("Lit Review", "It broke.")
        assert shown and shown[0][0] == "Lit Review" and shown[0][1] == "It broke."

    def test_a_dialog_that_fails_never_raises(self, windowed, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def boom(*args):
            raise OSError("no osascript")

        monkeypatch.setattr(ui, "_mac_dialog", boom)
        ui.show_error("Lit Review", "It broke.")  # must not raise

    def test_dialogs_can_be_turned_off(self, windowed, monkeypatch):
        monkeypatch.setenv("LIT_REVIEW_NO_DIALOG", "1")
        monkeypatch.setattr(ui, "_mac_dialog", lambda *a: pytest.fail("a dialog was shown"))
        ui.show_error("Lit Review", "It broke.")
        assert ui.confirm("Lit Review", "Sure?") is True

    def test_confirm_follows_the_button(self, windowed, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(ui, "_mac_dialog", lambda *a: "Quit")
        assert ui.confirm("Lit Review", "Quit?") is True
        monkeypatch.setattr(ui, "_mac_dialog", lambda *a: "Cancel")
        assert ui.confirm("Lit Review", "Quit?") is False
        monkeypatch.setattr(ui, "_mac_dialog", lambda *a: None)  # closed, or osascript failed
        assert ui.confirm("Lit Review", "Quit?") is False

    def test_the_mac_dialog_passes_text_as_arguments_not_script(self, monkeypatch):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="OK\n")

        monkeypatch.setattr(subprocess, "run", run)
        nasty = 'x" & (do shell script "echo pwned") & "'
        assert ui._mac_dialog("Title", nasty, ["OK"], "OK", "stop") == "OK"
        args = calls[0]
        assert args[-2:] == [nasty, "Title"]
        assert all(nasty not in part for part in args[:-2])

    def test_missing_streams_are_replaced(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        ui.ensure_streams()
        print("fine")  # would have been a no-op, but anything that .write()s must work
        sys.stderr.write("fine")


class TestLogFile:
    @pytest.fixture
    def log(self, tmp_path):
        path = logfile.setup(tmp_path / "logs")
        yield path
        logfile.teardown()

    def test_warnings_and_errors_are_kept(self, log):
        logging.getLogger("something").warning("a source failed")
        logging.getLogger("something").info("a request")
        text = log.read_text(encoding="utf-8")
        assert "a source failed" in text
        assert "a request" not in text

    def test_keys_in_a_message_or_traceback_never_reach_the_file(self, log):
        logger = logging.getLogger("something")
        logger.error("GET https://api.example/works?api_key=SECRET1&q=cats failed")
        try:
            raise RuntimeError("https://api.example/x?key=SECRET2 refused")
        except RuntimeError:
            logger.exception("lookup failed")
        logger.error("link %s", "http://127.0.0.1:8100/#token=SECRET3")
        text = log.read_text(encoding="utf-8")
        assert "SECRET" not in text
        assert "REDACTED" in text and "lookup failed" in text

    def test_setting_it_up_twice_adds_one_handler(self, tmp_path):
        before = len(logging.getLogger().handlers)
        logfile.setup(tmp_path / "logs")
        logfile.setup(tmp_path / "logs")
        try:
            assert len(logging.getLogger().handlers) == before + 1
        finally:
            logfile.teardown()
        assert len(logging.getLogger().handlers) == before

    def test_a_folder_that_cannot_be_written_is_not_fatal(self, tmp_path):
        blocker = tmp_path / "logs"
        blocker.write_text("a file, not a folder")
        assert logfile.setup(blocker) is None


class TestVersion:
    def test_source_runs_say_dev(self):
        assert version.__version__ == "0.0.0-dev"

    def test_about_says_where_things_are(self, client, isolated_data):
        body = client.get("/api/about").get_json()
        assert body == {
            "version": version.__version__,
            "data_dir": str(isolated_data / "data"),
            "log_dir": str(isolated_data / "data" / "logs"),
            "packaged": False,
        }


class TestJobsRunning:
    def test_it_follows_the_locks(self):
        assert app_module._jobs_running() is False
        with app_module._exclusive("run", 987654) as acquired:
            assert acquired and app_module._jobs_running() is True
        assert app_module._jobs_running() is False


class TestQuit:
    def test_quits_without_asking_when_idle(self, monkeypatch):
        monkeypatch.setattr(ui, "confirm", lambda *a, **k: pytest.fail("asked with nothing running"))
        assert app_module._confirm_quit() is True

    def test_asks_when_a_job_is_running(self, monkeypatch):
        answers = iter([False, True])
        monkeypatch.setattr(ui, "confirm", lambda *a, **k: next(answers))
        with app_module._exclusive("run", 987655):
            assert app_module._confirm_quit() is False
            assert app_module._confirm_quit() is True


class TestTrayChoice:
    def test_off_from_source(self):
        assert app_module._tray_wanted([]) is False

    def test_on_when_asked_for_or_packaged(self, monkeypatch):
        assert app_module._tray_wanted(["--tray"]) is True
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert app_module._tray_wanted([]) is True

    def test_tests_and_ci_can_turn_it_off(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert app_module._tray_wanted(["--no-tray"]) is False
        monkeypatch.setenv("LIT_REVIEW_NO_TRAY", "1")
        assert app_module._tray_wanted([]) is False


class FakeIcon:
    """pystray.Icon stand-in whose loop ends when stop() is called."""

    instances = []

    def __init__(self, name, image, title, menu):
        self.menu = menu
        self.visible = False
        self.stopped = False
        FakeIcon.instances.append(self)

    def run(self, setup=None):
        if setup:
            setup(self)

    def stop(self):
        self.stopped = True


class TestTray:
    @pytest.fixture
    def fake_pystray(self, monkeypatch):
        import types

        FakeIcon.instances.clear()
        module = types.SimpleNamespace(
            Icon=FakeIcon,
            Menu=lambda *items: list(items),
            MenuItem=lambda text, action, default=False: (text, action, default),
        )
        monkeypatch.setitem(sys.modules, "pystray", module)
        return module

    def test_no_backend_means_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pystray", None)  # import raises ImportError
        with pytest.raises(tray.TrayUnavailable):
            tray.Tray(lambda: None, lambda: None, lambda: True)

    def test_the_menu_and_quit(self, fake_pystray):
        opened, quits = [], iter([False, True])
        icon = tray.Tray(lambda: opened.append("app"), lambda: opened.append("logs"), lambda: next(quits))
        icon.run()
        fake = FakeIcon.instances[0]
        assert fake.visible
        labels = [item[0] for item in fake.menu]
        assert labels == ["Open Lit Review", "Open log folder", "Quit"]
        fake.menu[0][1](fake, None)
        fake.menu[1][1](fake, None)
        assert opened == ["app", "logs"]
        fake.menu[2][1](fake, fake.menu[2])  # declined: stays up
        assert not fake.stopped
        fake.menu[2][1](fake, fake.menu[2])  # confirmed
        assert fake.stopped

    def test_a_stop_before_the_loop_starts_still_ends_it(self, fake_pystray):
        icon = tray.Tray(lambda: None, lambda: None, lambda: True)
        icon.stop()  # the server died before the icon was up
        icon.run()
        assert FakeIcon.instances[0].stopped


class TestServeWithTray:
    class Server:
        def __init__(self, fail=False):
            self.fail, self.shut_down = fail, False

        def serve_forever(self):
            if self.fail:
                raise RuntimeError("boom")

        def shutdown(self):
            self.shut_down = True

    def test_a_dead_server_takes_the_icon_down_and_says_so(self, monkeypatch, tmp_path):
        errors, stopped = [], []

        class Icon:
            def __init__(self, *args):
                pass

            def run(self):
                while not stopped:  # the tray loop, until stop()
                    time.sleep(0.01)

            def stop(self):
                stopped.append(True)

        monkeypatch.setattr(tray, "Tray", Icon)
        monkeypatch.setattr(ui, "show_error", lambda title, message: errors.append(message))
        app_module._serve(self.Server(fail=True), lambda: None, tmp_path)
        assert stopped and errors and str(tmp_path) in errors[0]

    def test_no_tray_still_serves(self, monkeypatch, tmp_path):
        def unavailable(*args):
            raise tray.TrayUnavailable("no display")

        served = []
        monkeypatch.setattr(tray, "Tray", unavailable)
        server = self.Server()
        server.serve_forever = lambda: served.append(True)
        app_module._serve(server, lambda: None, tmp_path)
        assert served


class TestSelfCheck:
    def test_every_check_passes_from_source(self, tmp_path, monkeypatch):
        out = tmp_path / "report.json"
        monkeypatch.setenv("LIT_REVIEW_SELFCHECK_FILE", str(out))
        # static/index.html exists only after `npm run build`; the rest must pass.
        code = selfcheck.run()
        report = json.loads(out.read_text(encoding="utf-8"))
        failed = {name: why for name, why in report["checks"].items() if why != "ok"}
        if (bundle.resource_path("static") / "index.html").is_file():
            assert code == 0 and report["ok"] and not failed
        else:
            assert set(failed) == {"files"}
        assert report["version"] == version.__version__
        assert report["frozen"] is False

    def test_a_failure_is_reported_and_fails_the_run(self, tmp_path, monkeypatch):
        out = tmp_path / "report.json"
        monkeypatch.setenv("LIT_REVIEW_SELFCHECK_FILE", str(out))

        def broken():
            raise ModuleNotFoundError("No module named 'anyio'")

        monkeypatch.setitem(selfcheck.CHECKS, "sdk clients", broken)
        assert selfcheck.run() == 1
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["ok"] is False
        assert "anyio" in report["checks"]["sdk clients"]

    def test_the_flag_runs_it_without_starting_the_app(self, monkeypatch):
        monkeypatch.setattr(selfcheck, "run", lambda: 7)
        assert app_module.main(["--self-check"]) == 7

    def test_it_covers_every_provider(self):
        # The check takes its list from llm.PROVIDERS, so none can be left out.
        seen = []
        import importlib

        real = importlib.import_module
        selfcheck.importlib.import_module = lambda name, *a: (seen.append(name), real(name, *a))[1]
        try:
            selfcheck._check_provider_modules()
        finally:
            selfcheck.importlib.import_module = real
        assert set(llm.PROVIDERS.values()) <= set(seen)


class TestWhatShips:
    """Guards for what the packaged build is made from."""

    SPEC = (bundle.resource_path("pyinstaller.spec")).read_text(encoding="utf-8")

    def test_provider_modules_come_from_the_apps_own_table(self):
        # They are imported by name at run time, so a hand-typed list would silently
        # lose the next provider that is added.
        assert "llm.PROVIDERS" in self.SPEC
        assert 'collect_submodules("providers")' in self.SPEC
        for module in set(llm.PROVIDERS.values()) | {"providers.openai_compat"}:
            assert module.split(".")[1] in {p.stem for p in bundle.resource_path("providers").glob("*.py")}

    def test_data_and_keys_live_in_one_folder_named_for_the_app(self):
        # The packaged app must find the same database and saved keys as a source run, so the
        # name is fixed here and shared. It is "Lit Review" (like other apps' folders), one folder
        # deep: Windows would otherwise make "Lit Review\Lit Review". Asked in a fresh process
        # with no override, as a real run is.
        code = "import credentials, db; print(db.DB_PATH.parent); print(credentials.CONFIG_DIR)"
        clean = {k: v for k, v in os.environ.items() if k not in ("LIT_REVIEW_DATA_DIR", "LIT_REVIEW_CONFIG_DIR")}
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=bundle.resource_path(), env=clean, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        for line in result.stdout.split("\n")[:2]:
            folder = Path(line.strip())
            assert folder.name == "Lit Review"
            assert folder.parent.name != "Lit Review"
        import credentials

        assert credentials.APP_NAME == "Lit Review"

    def test_the_mac_identifier_is_the_released_one(self):
        # macOS treats a new identifier as a different app, so it is not changed lightly.
        assert 'BUNDLE_ID = "io.github.colinpetree.lit-review"' in self.SPEC

    def test_the_version_in_source_is_a_dev_marker_the_release_overwrites(self):
        assert version.__version__ == "0.0.0-dev"


class TestMacDiskImage:
    """Guards for the Mac download people use (a disk image) and the zip the updater uses.
    The steps themselves only run on a Mac runner; these keep the workflow from losing them."""

    WORKFLOW = (bundle.resource_path("..") / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def step(self, name):
        start = self.WORKFLOW.index(f"- name: {name}")
        end = self.WORKFLOW.find("\n      - ", start + 1)
        return self.WORKFLOW[start : end if end != -1 else len(self.WORKFLOW)]

    def test_the_image_is_made_on_macs_only_from_the_signed_app_after_the_smoke_test(self):
        step = self.step("Make the Mac disk image")
        assert "if: runner.os == 'macOS'" in step
        assert 'hdiutil create -volname "Lit Review" -srcfolder dmg -format UDZO' in step
        assert 'ditto "dist/Lit Review.app" "dmg/Lit Review.app"' in step  # the same app as the zip
        assert "ln -s /Applications dmg/Applications" in step
        assert self.WORKFLOW.index("Sign the macOS app ad hoc") < self.WORKFLOW.index("Run the built app")
        assert self.WORKFLOW.index("Run the built app") < self.WORKFLOW.index("Make the Mac disk image")

    def test_the_image_is_mounted_and_checked_and_always_detached(self):
        step = self.step("Make the Mac disk image")
        assert "trap cleanup EXIT" in step and "hdiutil detach" in step and "-force" in step
        assert "hdiutil verify" in step
        assert "-readonly" in step and "-nobrowse" in step
        assert "codesign --verify --deep --strict" in step  # what a user drags out is still signed
        assert '--self-check' in step  # and runs from the read-only volume
        assert "Applications\\nLit Review.app" in step  # nothing else is in the window

    def test_the_start_up_check_is_proved_on_the_runner(self):
        # mac_app.running_from_read_only_volume must see Applications as writable (or it would
        # block every install) and the image as read-only, and the app must refuse from the image.
        step = self.step("Make the Mac disk image")
        assert 'test "$(readonly_flag /Applications)" = 0' in step
        assert 'test "$(readonly_flag "$mnt")" = 1' in step
        assert "timeout=60" in step  # a hook that does not fire must fail the job, not hang it
        assert "got {code}" in step
        # and the run uses throwaway folders, never the runner's real ones, with no dialog
        assert "LIT_REVIEW_DATA_DIR" in step and "LIT_REVIEW_CONFIG_DIR" in step
        assert "LIT_REVIEW_NO_DIALOG=1 LIT_REVIEW_NO_BROWSER=1 LIT_REVIEW_NO_TRAY=1" in step  # as the smoke test
        # exit code 1 alone could be another start-up failure: a refusal also leaves no instance lock
        assert 'test ! -e "$LIT_REVIEW_DATA_DIR/instance.lock"' in step

    def test_both_files_are_uploaded_and_released(self):
        assert "path: out/*\n" in self.WORKFLOW  # the build uploads everything it made
        assert "path: out/*.zip" not in self.WORKFLOW
        release = self.WORKFLOW[self.WORKFLOW.index("\n  release:") :]
        assert "sha256sum *.zip *.dmg" in release
        assert "out/*.zip" in release and "out/*.dmg" in release

    def test_the_release_job_stops_unless_all_five_downloads_are_there(self):
        release = self.WORKFLOW[self.WORKFLOW.index("\n  release:") :]
        check = release[release.index("Check the downloads are all here") : release.index("- name: Checksums")]
        assert '"${#zips[@]}" -ne 3' in check and '"${#dmgs[@]}" -ne 2' in check
        assert "exit 1" in check
        assert release.index("Check the downloads are all here") < release.index("softprops/action-gh-release")

    def test_the_mac_zips_stay_for_the_updater(self):
        zip_step = self.step("Zip it")
        assert 'ditto -c -k --sequesterRsrc --keepParent "dist/Lit Review.app"' in zip_step
        assert ".dmg" not in zip_step  # the image has its own step


class TestConsoleDetection:
    class Stream:
        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    def test_source_runs_have_a_console_if_there_is_a_stream(self, monkeypatch):
        monkeypatch.setattr(sys, "stderr", self.Stream(False))
        assert ui._detect_console() is True

    def test_no_stream_is_no_console(self, monkeypatch):
        monkeypatch.setattr(sys, "stderr", None)
        assert ui._detect_console() is False

    def test_a_packaged_mac_app_has_streams_that_go_nowhere(self, monkeypatch):
        # Started from Finder: stderr exists but is not a terminal, so dialogs are needed.
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "stderr", self.Stream(False))
        assert ui._detect_console() is False

    def test_a_packaged_app_started_from_a_terminal_prints(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "stderr", self.Stream(True))
        assert ui._detect_console() is True


class TestLogFileKeepsRecordsIntact:
    def test_other_handlers_still_see_the_original_message_and_traceback(self, tmp_path):
        seen = []

        class Spy(logging.Handler):
            def emit(self, record):
                seen.append((record.getMessage(), record.exc_info))

        logfile.setup(tmp_path / "logs")
        spy = Spy()
        logging.getLogger().addHandler(spy)  # after ours, as caplog and the console are
        try:
            try:
                raise RuntimeError("x")
            except RuntimeError:
                logging.getLogger("t").exception("GET /x?key=SECRET1 failed")
        finally:
            logging.getLogger().removeHandler(spy)
            logfile.teardown()
        assert seen[0][0] == "GET /x?key=SECRET1 failed" and seen[0][1] is not None
