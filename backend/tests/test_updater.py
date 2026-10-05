"""The updater: download (with resume), staging, layout detection, the background pass and
the launch-time apply. No test reaches GitHub: HTTP is faked at `updater._open`/`source_http.get`."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

import app_settings
import db
import source_http
import update_manifest as um
import updater

SHA = "a" * 64


@pytest.fixture(autouse=True)
def clean_status():
    updater.reset_for_tests()
    yield
    updater.reset_for_tests()


class Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self.body, self.headers, self.closed = status, body, headers or {}, False

    @property
    def content(self):
        return self.body

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self):
        self.closed = True


def asset_for(data, name="Lit-Review-0.2.0-windows.zip", unpacked=300):
    return um.Asset("windows", name, len(data), unpacked, hashlib.sha256(data).hexdigest())


def serve(monkeypatch, body, ranges=True):
    """Fake `_open` serving `body`, honouring Range when `ranges`. Returns the request log."""
    log = []

    def fake(url, headers=None, stream=False):
        log.append(dict(headers or {}))
        rng = (headers or {}).get("Range")
        if rng and ranges:
            start = int(rng.split("=")[1].rstrip("-"))
            return Resp(206, body[start:])
        return Resp(200, body)

    monkeypatch.setattr(updater, "_open", fake)
    return log


class TestDownload:
    def test_downloads_and_verifies(self, tmp_path, monkeypatch):
        data = b"x" * 1000
        serve(monkeypatch, data)
        seen = []
        path = updater.download(asset_for(data), "v0.2.0", tmp_path, progress=seen.append)
        assert path.read_bytes() == data and not (tmp_path / (path.name + ".part")).exists()
        assert seen and seen[-1] == 1.0

    def test_resumes_a_partial_file_with_a_range_request(self, tmp_path, monkeypatch):
        data = bytes(range(256)) * 20
        asset = asset_for(data)
        (tmp_path / (asset.name + ".part")).write_bytes(data[:1500])
        log = serve(monkeypatch, data)
        assert updater.download(asset, "v0.2.0", tmp_path).read_bytes() == data
        assert log == [{"Range": "bytes=1500-"}]

    def test_a_server_that_ignores_range_restarts_cleanly(self, tmp_path, monkeypatch):
        data = b"abc" * 500
        asset = asset_for(data)
        (tmp_path / (asset.name + ".part")).write_bytes(b"zzz")
        serve(monkeypatch, data, ranges=False)
        assert updater.download(asset, "v0.2.0", tmp_path).read_bytes() == data

    def test_a_truncated_download_keeps_the_part_for_next_time(self, tmp_path, monkeypatch):
        data = b"q" * 1000
        asset = asset_for(data)
        monkeypatch.setattr(updater, "_open", lambda url, headers=None, stream=False: Resp(200, data[:400]))
        with pytest.raises(updater.UpdateError, match="resume"):
            updater.download(asset, "v0.2.0", tmp_path)
        assert (tmp_path / (asset.name + ".part")).stat().st_size == 400

    def test_a_hash_mismatch_deletes_the_file(self, tmp_path, monkeypatch):
        data = b"x" * 100
        asset = um.Asset("windows", "a.zip", 100, 300, SHA)
        serve(monkeypatch, data)
        with pytest.raises(updater.UpdateError, match="checksum"):
            updater.download(asset, "v0.2.0", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_more_than_the_signed_size_is_refused_and_deleted(self, tmp_path, monkeypatch):
        asset = um.Asset("windows", "a.zip", 50, 300, SHA)
        serve(monkeypatch, b"x" * 500)
        with pytest.raises(updater.UpdateError, match="larger"):
            updater.download(asset, "v0.2.0", tmp_path)
        assert not list(tmp_path.glob("*.part"))

    def test_an_oversized_partial_is_discarded_before_resuming(self, tmp_path, monkeypatch):
        data = b"d" * 100
        asset = asset_for(data)
        (tmp_path / (asset.name + ".part")).write_bytes(b"z" * 500)
        serve(monkeypatch, data)
        assert updater.download(asset, "v0.2.0", tmp_path).read_bytes() == data

    def test_an_already_verified_zip_is_not_downloaded_again(self, tmp_path, monkeypatch):
        data = b"k" * 100
        asset = asset_for(data)
        (tmp_path / asset.name).write_bytes(data)
        monkeypatch.setattr(updater, "_open", lambda *a, **k: pytest.fail("downloaded again"))
        assert updater.download(asset, "v0.2.0", tmp_path).read_bytes() == data

    def test_a_bad_status_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater, "_open", lambda url, headers=None, stream=False: Resp(404))
        with pytest.raises(updater.UpdateError, match="404"):
            updater.download(asset_for(b"x" * 10), "v0.2.0", tmp_path)

    def test_cancelling_stops_it(self, tmp_path, monkeypatch):
        serve(monkeypatch, b"x" * 10)
        with pytest.raises(updater.UpdateError, match="cancelled"):
            updater.download(asset_for(b"x" * 10), "v0.2.0", tmp_path, cancelled=lambda: True)


class TestOpen:
    """Redirects are followed by hand so every hop is checked against GitHub's hosts."""

    def fake_get(self, monkeypatch, replies):
        seen = []

        def get(label, url, **kwargs):
            seen.append((url, kwargs.get("allow_redirects")))
            return replies.pop(0)

        monkeypatch.setattr(source_http, "get", get)
        return seen

    def test_follows_a_redirect_to_githubs_asset_host(self, monkeypatch):
        seen = self.fake_get(monkeypatch, [
            Resp(302, headers={"Location": "https://release-assets.githubusercontent.com/x"}), Resp(200, b"ok")])
        assert updater._open("https://github.com/colinpetree/lit-review/releases/download/v1/a.zip").content == b"ok"
        assert [s[1] for s in seen] == [False, False]

    def test_refuses_a_redirect_to_another_host(self, monkeypatch):
        self.fake_get(monkeypatch, [Resp(302, headers={"Location": "https://evil.example.com/a.zip"})])
        with pytest.raises(updater.UpdateError, match="refusing"):
            updater._open("https://github.com/x")

    @pytest.mark.parametrize("url", ["http://github.com/x", "ftp://github.com/x", "https://github.com.evil.com/x", "https://evilgithub.com/x"])
    def test_refuses_non_https_and_lookalike_hosts(self, url):
        with pytest.raises(updater.UpdateError):
            updater._open(url)

    def test_gives_up_after_too_many_redirects(self, monkeypatch):
        self.fake_get(monkeypatch, [Resp(302, headers={"Location": "https://github.com/y"}) for _ in range(20)])
        with pytest.raises(updater.UpdateError, match="redirects"):
            updater._open("https://github.com/x")

    def test_a_connection_failure_becomes_an_update_error(self, monkeypatch):
        def get(*a, **k):
            raise source_http.SourceUnavailable("Could not reach GitHub.")

        monkeypatch.setattr(source_http, "get", get)
        with pytest.raises(updater.UpdateError):
            updater._open("https://github.com/x")


class TestTestOverrides:
    def test_the_base_override_is_ignored_without_the_testing_switch(self, monkeypatch):
        monkeypatch.setenv("LIT_REVIEW_UPDATE_BASE", "http://127.0.0.1:9")
        monkeypatch.delenv("LIT_REVIEW_TESTING", raising=False)
        assert updater.manifest_url("m.json").startswith("https://github.com/")
        with pytest.raises(updater.UpdateError):
            updater._open("http://127.0.0.1:9/m.json")

    def test_the_base_override_works_for_loopback_under_testing(self, monkeypatch):
        monkeypatch.setenv("LIT_REVIEW_UPDATE_BASE", "http://127.0.0.1:9/rel/")
        monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
        assert updater.manifest_url("m.json") == "http://127.0.0.1:9/rel/m.json"
        assert updater._host_ok("http://127.0.0.1:9/rel/m.json")

    def test_a_non_loopback_override_is_refused(self, monkeypatch):
        monkeypatch.setenv("LIT_REVIEW_UPDATE_BASE", "http://example.com")
        monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
        with pytest.raises(updater.UpdateError):
            updater.manifest_url("m.json")

    def test_the_thread_is_off_under_the_no_thread_switch(self, monkeypatch):
        monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
        assert updater.enabled()
        monkeypatch.setenv("LIT_REVIEW_NO_UPDATE_THREAD", "1")
        assert not updater.enabled()

    def test_a_source_run_never_updates(self, monkeypatch):
        monkeypatch.delenv("LIT_REVIEW_TESTING", raising=False)
        assert not updater.enabled()
        assert updater.start_background() is None
        assert updater.apply_at_launch() is False


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


class TestZipSafety:
    def test_a_normal_zip_names_its_top_folder(self, tmp_path):
        z = make_zip(tmp_path / "a.zip", {"Lit Review/app.exe": "x", "Lit Review/_internal/a.dll": "y"})
        assert updater.safe_members(z, 1000) == "Lit Review"

    @pytest.mark.parametrize(
        "name", ["../evil.exe", "Lit Review/../../evil.exe", "/abs/evil", "C:/evil.exe", "Lit Review\\a\\..\\b", "a/b\rc"]
    )
    def test_unsafe_names_are_refused(self, tmp_path, name):
        z = make_zip(tmp_path / "a.zip", {"Lit Review/ok.exe": "x", name: "y"})
        with pytest.raises(updater.UpdateError):
            updater.safe_members(z, 1000)

    def test_two_top_level_folders_are_refused(self, tmp_path):
        z = make_zip(tmp_path / "a.zip", {"A/x": "1", "B/x": "2"})
        with pytest.raises(updater.UpdateError, match="one top-level"):
            updater.safe_members(z, 1000)

    def test_a_zip_that_unpacks_to_more_than_signed_is_refused(self, tmp_path):
        z = make_zip(tmp_path / "a.zip", {"A/x": "z" * 5_000_000})
        with pytest.raises(updater.UpdateError, match="signed size"):
            updater.safe_members(z, 1000)

    def test_not_a_zip(self, tmp_path):
        (tmp_path / "a.zip").write_bytes(b"nope")
        with pytest.raises(updater.UpdateError, match="valid zip"):
            updater.safe_members(tmp_path / "a.zip", 1000)


class TestStage:
    def setup_install(self, tmp_path):
        install = tmp_path / "apps" / "Lit Review"
        install.mkdir(parents=True)
        (install / "app.exe").write_text("old")
        return install

    def zip_of(self, tmp_path, **extra):
        return make_zip(tmp_path / "u.zip", {"Lit Review/app.exe": "new", "Lit Review/_internal/x": "1", **extra})

    def test_unpacks_next_to_the_install_and_runs_the_check(self, tmp_path):
        install = self.setup_install(tmp_path)
        asset = um.Asset("windows", "u.zip", 1, 1000, SHA)
        checked = []
        new = updater.stage(self.zip_of(tmp_path), asset, "0.2.0", install, Path("app.exe"), check=lambda exe, v: checked.append((exe, v)))
        assert new == install.with_name("Lit Review.new") and (new / "app.exe").read_text() == "new"
        assert checked == [(new / "app.exe", "0.2.0")]
        assert not install.with_name("Lit Review.staging").exists()
        assert (install / "app.exe").read_text() == "old"  # the installed copy is untouched

    def test_a_failing_check_removes_the_staged_copy(self, tmp_path):
        install = self.setup_install(tmp_path)

        def check(exe, v):
            raise updater.UpdateError("failed its self-check")

        with pytest.raises(updater.UpdateError, match="self-check"):
            updater.stage(self.zip_of(tmp_path), um.Asset("windows", "u.zip", 1, 1000, SHA), "0.2.0", install, Path("app.exe"), check=check)
        assert not install.with_name("Lit Review.new").exists() and not install.with_name("Lit Review.staging").exists()

    def test_a_zip_without_the_program_file_is_refused(self, tmp_path):
        install = self.setup_install(tmp_path)
        z = make_zip(tmp_path / "u.zip", {"Lit Review/readme.txt": "x"})
        with pytest.raises(updater.UpdateError, match="program file"):
            updater.stage(z, um.Asset("windows", "u.zip", 1, 1000, SHA), "0.2.0", install, Path("app.exe"), check=lambda *a: None)
        assert not install.with_name("Lit Review.staging").exists()

    def test_an_older_leftover_is_replaced(self, tmp_path):
        install = self.setup_install(tmp_path)
        stale = install.with_name("Lit Review.new")
        stale.mkdir()
        (stale / "stale.txt").write_text("x")
        new = updater.stage(self.zip_of(tmp_path), um.Asset("windows", "u.zip", 1, 1000, SHA), "0.2.0", install, Path("app.exe"), check=lambda *a: None)
        assert not (new / "stale.txt").exists()


class TestSelfCheck:
    def run_with(self, monkeypatch, report, expected="0.2.0"):
        def fake_run(cmd, env=None, **kwargs):
            if report is not None:
                Path(env["LIT_REVIEW_SELFCHECK_FILE"]).write_text(json.dumps(report))

        monkeypatch.setattr(updater.subprocess, "run", fake_run)
        updater.self_check("x.exe", expected)

    def test_passes(self, monkeypatch):
        self.run_with(monkeypatch, {"ok": True, "version": "0.2.0"})

    def test_a_failing_report_is_refused(self, monkeypatch):
        with pytest.raises(updater.UpdateError, match="self-check"):
            self.run_with(monkeypatch, {"ok": False, "version": "0.2.0"})

    def test_the_wrong_version_is_refused(self, monkeypatch):
        with pytest.raises(updater.UpdateError, match="not 0.2.0"):
            self.run_with(monkeypatch, {"ok": True, "version": "0.1.9"})

    def test_no_report_is_refused(self, monkeypatch):
        with pytest.raises(updater.UpdateError):
            self.run_with(monkeypatch, None)


class TestLayout:
    def test_windows_layout(self, tmp_path):
        install = tmp_path / "Lit Review"
        (install / "_internal").mkdir(parents=True)
        assert updater.install_layout(install / "Lit Review.exe", "win32") == (install, Path("Lit Review.exe"))

    def test_windows_without_internal_is_unsupported(self, tmp_path):
        (tmp_path / "Lit Review").mkdir()
        with pytest.raises(updater.UpdateError, match="laid out"):
            updater.install_layout(tmp_path / "Lit Review" / "Lit Review.exe", "win32")

    def test_windows_path_too_long(self, tmp_path):
        install = tmp_path / ("d" * 160)  # not created: Windows itself cannot make a path this long
        with pytest.raises(updater.UpdateError, match="too long"):
            updater.install_layout(install / "Lit Review.exe", "win32")

    def test_mac_layout(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater.mac_app, "running_from_read_only_volume", lambda path: False)
        app = tmp_path / "Lit Review.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        exe = app / "Contents" / "MacOS" / "Lit Review"
        assert updater.install_layout(exe, "darwin") == (app, Path("Contents/MacOS/Lit Review"))

    def test_mac_read_only_or_translocated_is_unsupported(self, tmp_path, monkeypatch):
        app = tmp_path / "Lit Review.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        exe = app / "Contents" / "MacOS" / "Lit Review"
        monkeypatch.setattr(updater.mac_app, "running_from_read_only_volume", lambda path: True)
        with pytest.raises(updater.UpdateError, match="Applications"):
            updater.install_layout(exe, "darwin")
        translocated = tmp_path / "AppTranslocation" / "x" / "d" / "Lit Review.app"
        (translocated / "Contents" / "MacOS").mkdir(parents=True)
        monkeypatch.setattr(updater.mac_app, "running_from_read_only_volume", lambda path: False)
        with pytest.raises(updater.UpdateError, match="Applications"):
            updater.install_layout(translocated / "Contents" / "MacOS" / "Lit Review", "darwin")

    def test_other_systems_are_unsupported(self, tmp_path):
        with pytest.raises(updater.UpdateError, match="Windows and Mac"):
            updater.install_layout(tmp_path / "x", "linux")


def manifest(version="0.2.0", min_version=None):
    return um.Manifest(version, f"v{version}", "2026-10-05", "A note", min_version,
                       (um.Asset("windows", f"Lit-Review-{version}-windows.zip", 100, 300, SHA),))


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """check_once with every network and disk step faked; `calls` records what ran."""
    install = tmp_path / "apps" / "Lit Review"
    (install / "_internal").mkdir(parents=True)
    calls = []

    def fake_download(asset, tag, directory, progress=None, cancelled=None):
        calls.append("download")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / asset.name).write_bytes(b"zip")
        return directory / asset.name

    def fake_stage(zip_path, asset, version_text, inst, exe_rel, **kw):
        calls.append("stage")
        new = inst.with_name(inst.name + ".new")
        new.mkdir()
        return new

    monkeypatch.setattr(updater, "fetch_manifest", lambda running=None: (manifest(), b"raw"))
    monkeypatch.setattr(updater, "install_layout", lambda *a: (install, Path("app.exe")))
    monkeypatch.setattr(updater, "check_free_space", lambda d, a: None)
    monkeypatch.setattr(updater, "download", fake_download)
    monkeypatch.setattr(updater, "stage", fake_stage)
    monkeypatch.setattr(um, "asset_for", lambda m, plat=None: m.assets[0])
    monkeypatch.setattr(updater.version, "__version__", "0.1.0")
    return type("P", (), {"install": install, "calls": calls})


class TestCheckOnce:
    def test_downloads_and_stages_a_newer_release(self, pipeline):
        assert updater.check_once() is None
        assert pipeline.calls == ["download", "stage"]
        status = updater.status()
        assert status["state"] == "staged" and status["latest"] == "0.2.0" and status["notice"] == "A note"
        assert updater.load_state()["staged"]["version"] == "0.2.0"
        assert not list(updater.updates_dir().glob("*.zip"))  # the unpacked copy is used from here

    def test_nothing_newer_is_idle(self, pipeline, monkeypatch):
        def none(running=None):
            raise um.ManifestError("0.2.0 is not newer than 0.2.0")

        monkeypatch.setattr(updater, "fetch_manifest", none)
        assert updater.check_once() is None
        assert updater.status()["state"] == "idle" and pipeline.calls == []

    def test_a_network_failure_retries_later_without_crashing(self, pipeline, monkeypatch):
        def boom(running=None):
            raise updater.UpdateError("Could not reach GitHub")

        monkeypatch.setattr(updater, "fetch_manifest", boom)
        assert updater.check_once() == updater.RETRY_SECONDS[0]
        assert "GitHub" in updater.status()["error"]

    def test_required_follows_min_version(self, pipeline, monkeypatch):
        monkeypatch.setattr(updater, "fetch_manifest", lambda running=None: (manifest(min_version="0.1.5"), b"raw"))
        updater.check_once()
        assert updater.status()["required"] is True

    def test_nothing_is_downloaded_while_a_job_runs(self, pipeline):
        assert updater.check_once(jobs_running=lambda: True) == updater.BUSY_RETRY_SECONDS
        assert pipeline.calls == []

    def test_an_already_staged_release_is_not_fetched_again(self, pipeline):
        updater.check_once()
        pipeline.calls.clear()
        updater.check_once()
        assert pipeline.calls == [] and updater.status()["state"] == "staged"

    def test_a_newer_release_replaces_a_staged_one(self, pipeline, monkeypatch):
        updater.check_once()
        old_dir = Path(updater.load_state()["staged"]["dir"])
        monkeypatch.setattr(updater, "fetch_manifest", lambda running=None: (manifest("0.3.0"), b"raw"))
        pipeline.calls.clear()
        updater.check_once()
        assert pipeline.calls == ["download", "stage"]
        assert updater.load_state()["staged"]["version"] == "0.3.0"

    def test_an_unsupported_install_goes_quiet_with_one_state(self, pipeline, monkeypatch):
        def bad(*a):
            raise updater.UpdateError("move it somewhere you can change")

        monkeypatch.setattr(updater, "install_layout", bad)
        assert updater.check_once() is None
        assert updater.status()["state"] == "unsupported" and pipeline.calls == []

    def test_no_download_for_this_platform(self, pipeline, monkeypatch):
        monkeypatch.setattr(um, "asset_for", lambda m, plat=None: None)
        updater.check_once()
        assert updater.status()["state"] == "unsupported"

    def test_a_failed_stage_leaves_it_available_and_retries(self, pipeline, monkeypatch):
        def broken(*a, **k):
            raise updater.UpdateError("failed its self-check")

        monkeypatch.setattr(updater, "stage", broken)
        assert updater.check_once() == updater.RETRY_SECONDS[0]
        assert updater.status()["state"] == "available" and "self-check" in updater.status()["error"]
        assert "staged" not in updater.load_state()

    def test_a_version_given_up_on_is_not_retried(self, pipeline):
        updater.save_state({"failed": "0.2.0"})
        updater.check_once()
        assert pipeline.calls == [] and updater.status()["state"] == "failed"

    def test_this_versions_partial_download_survives_for_resume(self, pipeline):
        directory = updater.updates_dir()
        directory.mkdir(parents=True)
        mine, other = "Lit-Review-0.2.0-windows.zip.part", "Lit-Review-0.1.5-windows.zip.part"
        (directory / mine).write_bytes(b"half")
        (directory / other).write_bytes(b"old")
        calls = []
        orig = updater.download
        updater.download = lambda asset, tag, d, **kw: calls.append((d / mine).exists()) or orig(asset, tag, d, **kw)
        try:
            updater.check_once()
        finally:
            updater.download = orig
        assert calls == [True] and not (directory / other).exists()


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
    monkeypatch.setattr(updater.version, "__version__", "0.1.0")
    new = tmp_path / "apps" / "Lit Review.new"
    new.mkdir(parents=True)
    state = {"staged": {"version": "0.2.0", "dir": str(new), "min_version": None, "exe": "app.exe", "install": str(tmp_path / "apps" / "Lit Review")}}
    updater.save_state(state)
    return state["staged"]


class TestApplyAtLaunch:
    def test_off_means_nothing_is_applied(self, staged):
        launched = []
        assert updater.apply_at_launch(launch=launched.append) is False and launched == []

    def test_on_applies_and_counts_the_attempt(self, staged):
        app_settings.save(auto_apply=True)
        launched = []
        assert updater.apply_at_launch(launch=launched.append) is True
        assert launched == [staged] and updater.load_state()["attempts"] == {"0.2.0": 1}

    def test_below_min_version_applies_even_when_off(self, staged):
        state = updater.load_state()
        state["staged"]["min_version"] = "0.1.5"
        updater.save_state(state)
        launched = []
        assert updater.apply_at_launch(launch=launched.append) is True

    def test_at_or_above_min_version_and_off_does_not(self, staged):
        state = updater.load_state()
        state["staged"]["min_version"] = "0.1.0"
        updater.save_state(state)
        assert updater.apply_at_launch(launch=lambda s: None) is False

    def test_gives_up_after_two_attempts_and_discards_the_copy(self, staged):
        app_settings.save(auto_apply=True)
        for _ in range(updater.MAX_ATTEMPTS):
            assert updater.apply_at_launch(launch=lambda s: None) is True
        assert updater.apply_at_launch(launch=lambda s: pytest.fail("a third try")) is False
        state = updater.load_state()
        assert state["failed"] == "0.2.0" and "staged" not in state
        assert not Path(staged["dir"]).exists()

    def test_a_staged_copy_that_is_not_newer_is_ignored(self, staged, monkeypatch):
        app_settings.save(auto_apply=True)
        monkeypatch.setattr(updater.version, "__version__", "0.2.0")
        assert updater.apply_at_launch(launch=lambda s: pytest.fail("applied")) is False

    def test_a_missing_staged_folder_is_ignored(self, staged):
        app_settings.save(auto_apply=True)
        Path(staged["dir"]).rmdir()
        assert updater.apply_at_launch(launch=lambda s: pytest.fail("applied")) is False

    def test_a_helper_that_cannot_start_does_not_block_the_app(self, staged):
        app_settings.save(auto_apply=True)

        def fail(s):
            raise OSError("no")

        assert updater.apply_at_launch(launch=fail) is False

    def test_a_corrupt_state_file_is_nothing_staged(self, staged):
        updater._state_path().write_text("{not json")
        app_settings.save(auto_apply=True)
        assert updater.apply_at_launch(launch=lambda s: pytest.fail("applied")) is False


class TestStartApply:
    def test_starts_the_helper_for_the_staged_copy(self, staged):
        launched = []
        updater.start_apply(launch=lambda s: launched.append(s) or "proc")
        assert launched == [staged] and updater.status()["state"] == "applying"

    def test_nothing_staged_is_an_error(self, tmp_path):
        with pytest.raises(updater.UpdateError, match="no update ready"):
            updater.start_apply(launch=lambda s: None)

    def test_a_launch_failure_is_reported_and_state_returns_to_staged(self, staged):
        def fail(s):
            raise OSError("denied")

        with pytest.raises(updater.UpdateError):
            updater.start_apply(launch=fail)
        assert updater.status()["state"] == "staged"


class TestAfterRestart:
    def test_marker_is_written_only_by_the_version_that_was_staged(self, staged, monkeypatch):
        monkeypatch.setattr(updater.version, "__version__", "0.1.0")
        updater.write_started_marker()
        assert not (updater.updates_dir() / updater.MARKER_NAME).exists()
        updater.write_started_marker("0.2.0")
        assert json.loads((updater.updates_dir() / updater.MARKER_NAME).read_text()) == {"version": "0.2.0"}

    def test_a_successful_install_clears_the_staged_state(self, staged):
        state = updater.load_state()
        state["attempts"] = {"0.2.0": 1}
        updater.save_state(state)
        (updater.updates_dir() / updater.RESULT_NAME).write_text(json.dumps({"status": "installed", "version": "0.2.0"}))
        assert updater.take_result("0.2.0") is None
        assert updater.load_state() == {"attempts": {}}
        assert not (updater.updates_dir() / updater.RESULT_NAME).exists()

    def test_a_rolled_back_install_gives_a_message_once(self, staged):
        (updater.updates_dir() / updater.RESULT_NAME).write_text(
            json.dumps({"status": "rolled_back", "version": "0.2.0", "reason": "A system security prompt may have blocked it."}))
        message = updater.take_result("0.1.0")
        assert "0.2.0" in message and "still on version 0.1.0" in message and "security prompt" in message
        assert updater.take_result("0.1.0") is None

    def test_no_result_means_no_message(self, staged):
        assert updater.take_result("0.1.0") is None

    def test_note_failure_shows_on_the_page(self):
        updater.note_failure("It did not work.")
        status = updater.status()
        assert status["state"] == "failed" and status["error"] == "It did not work." and status["url"]


class TestLaunchHelper:
    def test_builds_an_argument_list_with_the_paths_as_arguments(self, tmp_path, monkeypatch):
        fake_helper = tmp_path / "update_helper.py"
        fake_helper.write_text("print('hi')")
        monkeypatch.setattr(updater, "helper_command", lambda: [str(fake_helper)])
        staged = {"install": str(tmp_path / "100% & ^!"), "dir": str(tmp_path / "100% & ^!.new"), "exe": "app.exe", "version": "0.2.0"}
        seen = {}

        def popen(args, **kwargs):
            seen["args"], seen["kwargs"] = args, kwargs
            return "proc"

        assert updater.launch_helper(staged, popen=popen) == "proc"
        args = seen["args"]
        assert isinstance(args, list) and "shell" not in seen["kwargs"]
        assert Path(args[0]).parent != tmp_path  # run from a copy in a scratch folder
        assert args[args.index("--install") + 1] == staged["install"]
        assert args[args.index("--old") + 1] == staged["install"] + ".old"
        assert args[args.index("--version") + 1] == "0.2.0"
        assert "--pid" in args and "--marker" in args and "--result" in args

    def test_the_database_is_backed_up_and_only_the_newest_kept(self, tmp_path, monkeypatch):
        db.ensure_ready()
        fake_helper = tmp_path / "update_helper.py"
        fake_helper.write_text("")
        monkeypatch.setattr(updater, "helper_command", lambda: [str(fake_helper)])
        directory = updater.updates_dir()
        directory.mkdir(parents=True)
        (directory / "before-update-0.0.9.db").write_bytes(b"old")
        staged = {"install": str(tmp_path / "a"), "dir": str(tmp_path / "a.new"), "exe": "x", "version": "0.2.0"}
        updater.launch_helper(staged, popen=lambda *a, **k: None)
        assert [p.name for p in directory.glob("before-update-*.db")] == [f"before-update-{updater.version.__version__}.db"]


class TestCleanup:
    def test_removes_leftover_folders_and_unwanted_staged_copy(self, tmp_path, monkeypatch):
        install = tmp_path / "Lit Review"
        install.mkdir()
        for suffix in (".old", ".failed", ".staging", ".new"):
            (tmp_path / ("Lit Review" + suffix)).mkdir()
        updater.cleanup_stale(install)
        assert [p.name for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith("Lit Review")] == ["Lit Review"]

    def test_keeps_a_staged_copy_that_is_still_wanted(self, staged, tmp_path):
        install = Path(staged["install"])
        install.mkdir()
        updater.cleanup_stale(install)
        assert Path(staged["dir"]).exists()

    def test_keeps_the_marker_a_waiting_helper_is_looking_for_and_removes_stale_partials(self, tmp_path):
        directory = updater.updates_dir()
        directory.mkdir(parents=True)
        (directory / updater.MARKER_NAME).write_text("{}")
        old = directory / "a.zip.part"
        old.write_bytes(b"x")
        import os
        import time

        os.utime(old, (time.time() - 5 * 86400,) * 2)
        fresh = directory / "b.zip.part"
        fresh.write_bytes(b"x")
        updater.cleanup_stale(tmp_path / "missing")
        # main() writes the marker just before cleanup runs; deleting it would make the helper
        # roll back a perfectly good update.
        assert (directory / updater.MARKER_NAME).exists() and not old.exists() and fresh.exists()

    def test_old_helper_copies_in_the_temp_folder_are_removed_but_recent_ones_are_not(self, tmp_path, monkeypatch):
        import os
        import time

        monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
        stale, recent = tmp_path / "lit-review-update-aaa", tmp_path / "lit-review-update-bbb"
        for folder in (stale, recent):
            folder.mkdir()
        os.utime(stale, (time.time() - 3 * 86400,) * 2)
        updater.cleanup_stale(tmp_path / "missing")
        assert not stale.exists() and recent.exists()


class TestReviewFixes:
    def test_a_mac_zip_with_resource_fork_sidecars_still_has_one_top_folder(self, tmp_path):
        z = make_zip(tmp_path / "a.zip", {"Lit Review.app/Contents/x": "1", "__MACOSX/Lit Review.app/._x": "2"})
        assert updater.safe_members(z, 1000) == "Lit Review.app"

    def test_the_sidecar_folder_is_still_checked_for_unsafe_names(self, tmp_path):
        z = make_zip(tmp_path / "a.zip", {"Lit Review.app/x": "1", "__MACOSX/../evil": "2"})
        with pytest.raises(updater.UpdateError, match="unsafe"):
            updater.safe_members(z, 1000)

    def test_a_folder_that_cannot_really_be_written_is_unsupported_even_if_os_access_says_yes(self, tmp_path, monkeypatch):
        install = tmp_path / "Lit Review"
        (install / "_internal").mkdir(parents=True)

        def refuse(*args, **kwargs):
            raise PermissionError("Program Files")

        monkeypatch.setattr(updater.tempfile, "TemporaryDirectory", refuse)
        with pytest.raises(updater.UpdateError, match="cannot change"):
            updater.install_layout(install / "Lit Review.exe", "win32")

    def test_a_writable_folder_leaves_no_probe_behind(self, tmp_path):
        install = tmp_path / "Lit Review"
        (install / "_internal").mkdir(parents=True)
        updater.install_layout(install / "Lit Review.exe", "win32")
        assert [p.name for p in tmp_path.iterdir()] == ["Lit Review"]

    def test_installing_does_not_drop_a_newer_release_staged_in_the_meantime(self, staged):
        state = updater.load_state()
        state["staged"] = {**state["staged"], "version": "0.3.0"}
        updater.save_state(state)
        (updater.updates_dir() / updater.RESULT_NAME).write_text(json.dumps({"status": "installed", "version": "0.2.0"}))
        updater.take_result("0.2.0")
        assert updater.load_state()["staged"]["version"] == "0.3.0"

    def test_a_release_without_a_manifest_is_nothing_to_offer_not_an_error(self, monkeypatch):
        monkeypatch.setattr(updater, "_open", lambda url, headers=None, stream=False: Resp(404))
        monkeypatch.setattr(updater.version, "__version__", "0.1.0")
        assert updater.check_once() is None
        assert updater.status()["state"] == "idle" and updater.status()["error"] == ""

    def test_a_check_does_not_disturb_an_install_under_way(self, pipeline):
        updater._set(state="applying")
        assert updater.check_once() is None
        assert pipeline.calls == [] and updater.status()["state"] == "applying"
