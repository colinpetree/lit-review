"""The update helper's swap logic, run on real temp folders with injected failures.

The helper is a standalone stdlib program (packaging/update_helper.py), loaded by path."""

import importlib.util
import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("update_helper", ROOT / "packaging" / "update_helper.py")
helper = importlib.util.module_from_spec(_spec)
sys.modules["update_helper"] = helper
_spec.loader.exec_module(helper)

EXE = "app.exe"


class Clock:
    """A fake clock: sleeping advances it, so retry loops finish instantly."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tree(tmp_path):
    """install (the running version), install.new (staged), nothing else."""
    install, new = tmp_path / "Lit Review", tmp_path / "Lit Review.new"
    for folder, text in ((install, "old"), (new, "new")):
        folder.mkdir()
        (folder / EXE).write_text(text)
    return Namespace(install=install, new=new, old=tmp_path / "Lit Review.old", failed=tmp_path / "Lit Review.failed", root=tmp_path)


def text(folder):
    return (folder / EXE).read_text()


def failing_rename(clock, fail_when):
    """os.rename, except calls for which fail_when(src, dst, call_number) is true raise."""
    calls = []

    def rename(src, dst):
        calls.append((Path(src).name, Path(dst).name))
        if fail_when(Path(src), Path(dst), len(calls)):
            raise PermissionError("in use")
        os.rename(src, dst)

    rename.calls = calls
    return rename


class TestSwap:
    def test_success(self, tree, clock):
        assert helper.swap(tree.install, tree.new, tree.old, sleep=clock.sleep, clock=clock)[0] == helper.SWAPPED
        assert text(tree.install) == "new" and text(tree.old) == "old" and not tree.new.exists()

    def test_first_rename_fails_then_succeeds(self, tree, clock):
        rename = failing_rename(clock, lambda s, d, n: n <= 3)
        assert helper.swap(tree.install, tree.new, tree.old, rename=rename, sleep=clock.sleep, clock=clock)[0] == helper.SWAPPED
        assert text(tree.install) == "new"

    def test_first_rename_never_works_changes_nothing(self, tree, clock):
        rename = failing_rename(clock, lambda s, d, n: s == tree.install)
        outcome, detail = helper.swap(tree.install, tree.new, tree.old, rename=rename, sleep=clock.sleep, clock=clock, timeout=5)
        assert outcome == helper.UNCHANGED and detail == "in use"
        assert text(tree.install) == "old" and text(tree.new) == "new" and not tree.old.exists()

    def test_second_rename_fails_and_the_old_build_is_put_back(self, tree, clock):
        rename = failing_rename(clock, lambda s, d, n: s == tree.new)
        outcome, detail = helper.swap(tree.install, tree.new, tree.old, rename=rename, sleep=clock.sleep, clock=clock, timeout=5)
        assert outcome == helper.RESTORED
        assert text(tree.install) == "old" and text(tree.new) == "new" and not tree.old.exists()

    def test_both_fail_is_reported_as_stranded(self, tree, clock):
        rename = failing_rename(clock, lambda s, d, n: s in (tree.new, tree.old))
        outcome, detail = helper.swap(tree.install, tree.new, tree.old, rename=rename, sleep=clock.sleep, clock=clock, timeout=5)
        assert outcome == helper.STRANDED
        assert not tree.install.exists() and tree.old.exists() and tree.new.exists()

    def test_the_second_rename_happens_immediately_after_the_first(self, tree, clock):
        rename = failing_rename(clock, lambda s, d, n: False)
        helper.swap(tree.install, tree.new, tree.old, rename=rename, sleep=clock.sleep, clock=clock)
        assert rename.calls == [("Lit Review", "Lit Review.old"), ("Lit Review.new", "Lit Review")]
        assert clock.now == 0  # no waiting between the two


class TestRollBack:
    def test_the_failed_tree_is_set_aside_and_the_old_one_restored(self, tree, clock):
        helper.swap(tree.install, tree.new, tree.old, sleep=clock.sleep, clock=clock)
        assert helper.roll_back(tree.install, tree.old, tree.failed, sleep=clock.sleep, clock=clock)
        assert text(tree.install) == "old" and text(tree.failed) == "new" and not tree.old.exists()

    def test_reports_failure_when_the_old_build_cannot_be_put_back(self, tree, clock):
        helper.swap(tree.install, tree.new, tree.old, sleep=clock.sleep, clock=clock)
        rename = failing_rename(clock, lambda s, d, n: s == tree.old)
        assert not helper.roll_back(tree.install, tree.old, tree.failed, rename=rename, sleep=clock.sleep, clock=clock, timeout=3)


class TestMarker:
    def test_matching_version(self, tmp_path):
        marker = tmp_path / "started.json"
        marker.write_text(json.dumps({"version": "0.2.0"}))
        assert helper.marker_ok(marker, "0.2.0")

    @pytest.mark.parametrize("content", [None, "", "{bad", "[]", '{"version": "0.1.0"}', '{"version": 2}'])
    def test_anything_else_is_not_ok(self, tmp_path, content):
        marker = tmp_path / "started.json"
        if content is not None:
            marker.write_text(content)
        assert not helper.marker_ok(marker, "0.2.0")

    def test_wait_returns_true_when_the_marker_appears(self, tmp_path, clock):
        marker = tmp_path / "started.json"
        polls = []

        def sleep(seconds):
            polls.append(seconds)
            clock.sleep(seconds)
            if len(polls) == 3:
                marker.write_text(json.dumps({"version": "0.2.0"}))

        assert helper.wait_for_marker(marker, "0.2.0", 90, sleep=sleep, clock=clock)

    def test_wait_gives_up_after_the_timeout(self, tmp_path, clock):
        assert not helper.wait_for_marker(tmp_path / "none.json", "0.2.0", 10, sleep=clock.sleep, clock=clock)
        assert clock.now >= 10

    def test_wait_stops_early_when_the_new_process_has_died(self, tmp_path, clock):
        assert not helper.wait_for_marker(tmp_path / "none.json", "0.2.0", 90, sleep=clock.sleep, clock=clock, alive=lambda: False)
        assert clock.now < 1

    def test_a_marker_for_another_version_does_not_count(self, tmp_path, clock):
        marker = tmp_path / "started.json"
        marker.write_text(json.dumps({"version": "0.1.0"}))
        assert not helper.wait_for_marker(marker, "0.2.0", 3, sleep=clock.sleep, clock=clock)


class TestWaitForExit:
    def test_returns_at_once_when_it_is_gone(self, clock):
        assert helper.wait_for_exit(1, 30, running=lambda pid: False, sleep=clock.sleep, clock=clock)
        assert clock.now == 0

    def test_terminates_a_process_that_will_not_close(self, clock):
        state = {"alive": True, "terminated": False}

        def terminate(pid):
            state["terminated"] = True
            state["alive"] = False

        assert helper.wait_for_exit(1, 30, running=lambda pid: state["alive"], terminate=terminate, sleep=clock.sleep, clock=clock)
        assert state["terminated"] and clock.now >= 30

    def test_false_when_even_terminate_does_not_work(self, clock):
        assert not helper.wait_for_exit(1, 5, running=lambda pid: True, terminate=lambda pid: None, sleep=clock.sleep, clock=clock)

    def test_this_process_is_seen_running_and_a_dead_pid_is_not(self):
        assert helper.pid_running(os.getpid())
        assert not helper.pid_running(0)


def args_for(tree, **overrides):
    values = dict(
        install=str(tree.install), new=str(tree.new), old=str(tree.old), exe=EXE, pid=1,
        marker=str(tree.root / "updates" / "started.json"), version="0.2.0",
        result=str(tree.root / "updates" / "result.json"), wait_seconds=1,
    )
    values.update(overrides)
    return Namespace(**values)


class TestValidate:
    def test_good_arguments(self, tree):
        install, new, old, exe, marker, result = helper.validate(args_for(tree))
        assert (install, new, old) == (tree.install, tree.new, tree.old)

    @pytest.mark.parametrize(
        "change",
        [
            {"install": "relative/path"},
            {"new": ""},
            {"old": "C:\\x\ny" if os.name == "nt" else "/x\ny"},
            {"exe": "../evil.exe"},
            {"exe": "missing.exe"},
            {"exe": "/abs.exe"},
        ],
    )
    def test_bad_arguments_are_refused(self, tree, change):
        with pytest.raises(helper.ArgumentError):
            helper.validate(args_for(tree, **change))

    def test_folders_must_share_a_parent_and_differ(self, tree, tmp_path):
        other = tmp_path / "elsewhere"
        other.mkdir()
        (other / EXE).write_text("x")
        with pytest.raises(helper.ArgumentError):
            helper.validate(args_for(tree, new=str(other / "n")))
        with pytest.raises(helper.ArgumentError):
            helper.validate(args_for(tree, new=str(tree.install)))

    def test_an_existing_old_folder_is_refused(self, tree):
        tree.old.mkdir()
        with pytest.raises(helper.ArgumentError):
            helper.validate(args_for(tree))

    def test_awkward_characters_in_a_path_are_fine(self, tmp_path):
        install, new = tmp_path / "100% & ^!", tmp_path / "100% & ^!.new"
        for folder in (install, new):
            folder.mkdir()
            (folder / EXE).write_text("x")
        ns = Namespace(install=str(install), new=str(new), old=str(tmp_path / "100% & ^!.old"), exe=EXE,
                       marker=str(tmp_path / "m.json"), result=str(tmp_path / "r.json"))
        helper.validate(ns)


class Child:
    def __init__(self, alive=True):
        self.alive, self.terminated = alive, False

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated = True


class Recorder:
    """Stands in for starting the app, waiting and cleaning up; records what the helper did."""

    def __init__(self, tree, marker_appears=True, exited=True):
        self.tree, self.marker_appears, self.exited = tree, marker_appears, exited
        self.started, self.cleaned, self.child = [], [], Child()

    def start(self, exe, extra=()):
        self.started.append((Path(exe), tuple(extra), text(Path(exe).parent)))
        return self.child

    def wait_exit(self, pid, timeout):
        return self.exited

    def marker_wait(self, marker, version, timeout, alive=None):
        return self.marker_appears

    def cleanup(self, path):
        self.cleaned.append(Path(path).name)
        return True


def run(tree, rec, args=None, **overrides):
    kwargs = dict(start=rec.start, wait_exit=rec.wait_exit, marker_wait=rec.marker_wait, cleanup=rec.cleanup)
    kwargs.update(overrides)
    return helper.run(args or args_for(tree), **kwargs)


def result_of(tree):
    return json.loads((tree.root / "updates" / "result.json").read_text())


class TestStartApp:
    def test_the_app_is_started_with_a_fresh_environment_and_an_argument_list(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "/helper/temp")
        monkeypatch.setattr(helper.subprocess, "Popen", lambda args, **kwargs: seen.update(args=args, **kwargs) or "proc")
        assert helper.start_app(tmp_path / "app.exe", ["--after-update"]) == "proc"
        assert seen["args"] == [str(tmp_path / "app.exe"), "--after-update"] and "shell" not in seen
        assert seen["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        assert seen["cwd"] == str(tmp_path)


class TestRun:
    def test_success_starts_the_new_build_with_after_update_and_cleans_up(self, tree):
        rec = Recorder(tree)
        assert run(tree, rec) == 0
        assert rec.started == [(tree.install / EXE, ("--after-update",), "new")]
        assert rec.cleaned == ["Lit Review.old"]
        assert result_of(tree)["status"] == "installed"

    def test_a_new_build_that_never_comes_up_is_rolled_back_and_the_old_one_restarted(self, tree):
        rec = Recorder(tree, marker_appears=False)
        assert run(tree, rec) == 1
        assert [s[2] for s in rec.started] == ["new", "old"]  # new tried, then the old one started
        assert rec.child.terminated
        assert text(tree.install) == "old"
        assert result_of(tree)["status"] == "rolled_back"
        assert "security" in result_of(tree)["reason"]

    def test_a_folder_that_cannot_be_renamed_keeps_the_old_version_running(self, tree):
        rec = Recorder(tree)
        assert run(tree, rec, do_swap=lambda *a: (helper.UNCHANGED, "in use")) == 1
        assert [s[2] for s in rec.started] == ["old"]
        assert result_of(tree)["status"] == "not_installed"

    def test_the_reason_carries_the_operating_systems_own_words(self, tree):
        rec = Recorder(tree)
        run(tree, rec, do_swap=lambda *a: (helper.UNCHANGED, "[WinError 5] Access is denied"))
        assert "Access is denied" in result_of(tree)["reason"] and "replace the old folder" in result_of(tree)["reason"]

    def test_a_new_build_that_never_wrote_its_marker_says_how_long_it_waited(self, tree):
        rec = Recorder(tree, marker_appears=False)
        run(tree, rec)
        assert "not ready after 1 seconds" in result_of(tree)["reason"]  # args_for waits 1 second

    def test_a_stranded_install_is_reported_and_nothing_is_started(self, tree):
        rec = Recorder(tree)
        assert run(tree, rec, do_swap=lambda *a: (helper.STRANDED, "in use")) == 2
        assert rec.started == []
        assert result_of(tree)["status"] == "stranded"

    def test_an_old_process_that_will_not_close_changes_nothing(self, tree):
        rec = Recorder(tree, exited=False)
        assert run(tree, rec) == 1
        assert rec.started == [] and text(tree.install) == "old" and tree.new.exists()
        assert result_of(tree)["status"] == "not_installed"

    def test_bad_arguments_report_and_start_nothing(self, tree):
        rec = Recorder(tree)
        assert run(tree, rec, args_for(tree, exe="missing.exe")) == 1
        assert rec.started == [] and result_of(tree)["status"] == "not_installed"

    def test_a_stale_marker_from_an_earlier_attempt_is_removed_first(self, tree):
        marker = tree.root / "updates" / "started.json"
        marker.parent.mkdir()
        marker.write_text(json.dumps({"version": "0.2.0"}))
        seen = []
        rec = Recorder(tree)
        run(tree, rec, marker_wait=lambda m, v, t, alive=None: seen.append(Path(m).exists()) or True)
        assert seen == [False]

    def test_a_new_program_that_cannot_be_started_is_rolled_back_not_left_in_place(self, tree):
        rec = Recorder(tree)
        calls = []

        def start(exe, extra=()):
            calls.append(text(Path(exe).parent))
            if len(calls) == 1:
                raise OSError("blocked by security software")
            return rec.child

        assert run(tree, rec, start=start, do_swap=helper.swap, do_roll_back=helper.roll_back) == 1
        assert text(tree.install) == "old" and calls == ["new", "old"]
        assert result_of(tree)["status"] == "rolled_back"

    def test_an_old_program_that_cannot_be_restarted_does_not_crash_the_helper(self, tree):
        rec = Recorder(tree)

        def start(exe, extra=()):
            raise OSError("no")

        assert run(tree, rec, start=start, do_swap=lambda *a: (helper.UNCHANGED, "in use")) == 1
        assert result_of(tree)["status"] == "not_installed"

    def test_the_real_swap_end_to_end(self, tree):
        rec = Recorder(tree)
        assert run(tree, rec, do_swap=helper.swap, do_roll_back=helper.roll_back) == 0
        assert text(tree.install) == "new"


class TestWhatShips:
    """Guards for how the helper reaches the user, in the style of the other packaging tests."""

    SPEC = (ROOT / "backend" / "pyinstaller.spec").read_text(encoding="utf-8")
    WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_the_helper_is_built_before_the_app_and_goes_inside_it(self):
        build_helper = self.WORKFLOW.index("pyinstaller packaging/update_helper.py")
        build_app = self.WORKFLOW.index("pyinstaller backend/pyinstaller.spec")
        assert build_helper < build_app
        assert "datas += [(str(HELPER), \".\")]" in self.SPEC

    def test_a_build_without_the_helper_stops(self):
        assert "if not HELPER.is_file():" in self.SPEC and "raise SystemExit" in self.SPEC

    def test_the_helper_has_no_console_window_on_windows(self):
        assert "--noconsole" in self.WORKFLOW

    def test_it_is_built_before_the_mac_app_is_signed(self):
        assert self.WORKFLOW.index("update_helper.py") < self.WORKFLOW.index("codesign --force --deep")

    def test_the_packaged_self_check_requires_and_runs_it(self):
        source = (ROOT / "backend" / "selfcheck.py").read_text(encoding="utf-8")
        assert "updater.HELPER_NAME" in source and '"--help"' in source
        assert '"update signing": _check_update_signing' in source

    def test_the_smoke_test_never_lets_the_packaged_app_reach_github(self):
        source = (ROOT / "packaging" / "smoke_test.py").read_text(encoding="utf-8")
        assert 'LIT_REVIEW_NO_UPDATE_THREAD="1"' in source and 'LIT_REVIEW_TESTING="1"' in source

    def test_the_helper_is_stdlib_only(self):
        source = (ROOT / "packaging" / "update_helper.py").read_text(encoding="utf-8")
        imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
        assert imports <= set(sys.stdlib_module_names), imports - set(sys.stdlib_module_names)
