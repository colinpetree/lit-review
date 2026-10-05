"""The third-party notices: where the app finds them, and the route Settings reads them from."""

import importlib.util
import sys

import pytest

import bundle
import notices

ROOT = bundle.resource_path().parent


@pytest.fixture
def source_dir(tmp_path, monkeypatch):
    """A stand-in for packaging/build/, where a source run's make_notices.py writes."""
    monkeypatch.setattr(notices, "SOURCE_BUILD_DIR", tmp_path / "build")
    (tmp_path / "build").mkdir()
    return tmp_path / "build"


class TestFindNotices:
    def test_none_when_nothing_was_built(self, source_dir):
        assert notices.find_notices() is None

    def test_a_source_run_uses_the_build_folder(self, source_dir):
        (source_dir / notices.FILE_NAME).write_text("from the build folder", encoding="utf-8")
        assert notices.find_notices() == source_dir / notices.FILE_NAME

    def test_a_packaged_app_uses_its_licenses_folder(self, source_dir, tmp_path, monkeypatch):
        (source_dir / notices.FILE_NAME).write_text("from the build folder", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "app"), raising=False)
        (tmp_path / "app" / "licenses").mkdir(parents=True)
        packaged = tmp_path / "app" / "licenses" / notices.FILE_NAME
        packaged.write_text("what shipped", encoding="utf-8")
        assert notices.find_notices() == packaged

    def test_a_packaged_app_never_reaches_for_the_source_folder(self, source_dir, tmp_path, monkeypatch):
        # The source path means nothing inside a frozen app, so a missing packaged file is "none".
        (source_dir / notices.FILE_NAME).write_text("from the build folder", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "empty"), raising=False)
        assert notices.find_notices() is None


class TestRoute:
    def test_returns_the_text(self, client, source_dir):
        (source_dir / notices.FILE_NAME).write_text("Lit Review includes the following\nMIT licensed", encoding="utf-8")
        response = client.get("/api/notices")
        assert response.status_code == 200
        assert response.get_json() == {"text": "Lit Review includes the following\nMIT licensed"}

    def test_says_plainly_when_there_is_no_file(self, client, source_dir):
        response = client.get("/api/notices")
        assert response.status_code == 404
        assert "make_notices.py" in response.get_json()["error"]

    def test_a_file_over_the_size_cap_is_not_opened(self, client, source_dir, monkeypatch):
        monkeypatch.setattr(notices, "MAX_BYTES", 10)
        (source_dir / notices.FILE_NAME).write_text("x" * 11, encoding="utf-8")
        response = client.get("/api/notices")
        assert response.status_code == 500
        assert "larger than expected" in response.get_json()["error"]

    def test_text_that_is_not_utf8_still_comes_back(self, client, source_dir):
        (source_dir / notices.FILE_NAME).write_bytes(b"caf\xe9 license")
        assert client.get("/api/notices").get_json()["text"].endswith("license")

    def test_it_needs_the_session_secret(self, client, source_dir):
        (source_dir / notices.FILE_NAME).write_text("x", encoding="utf-8")
        assert client.get("/api/notices", headers={"Authorization": "Bearer not-the-secret"}).status_code == 401
        assert client.get("/api/notices", headers={"Authorization": ""}).status_code == 401

    def test_the_request_cannot_choose_the_file(self, client, source_dir, tmp_path):
        (tmp_path / "secret.txt").write_text("not for you", encoding="utf-8")
        response = client.get("/api/notices?path=../secret.txt&file=../secret.txt")
        assert response.status_code == 404  # still "no notices": the query was ignored


class TestWhatShips:
    SPEC = bundle.resource_path("pyinstaller.spec").read_text(encoding="utf-8")

    def test_the_license_and_notices_go_inside_the_app(self):
        assert '(str(ROOT / "LICENSE"), "licenses")' in self.SPEC
        assert '(str(NOTICES), "licenses")' in self.SPEC
        assert "THIRD_PARTY_NOTICES.txt" in self.SPEC

    def test_a_build_without_the_notices_stops(self):
        assert "if not NOTICES.is_file():" in self.SPEC
        assert "raise SystemExit" in self.SPEC

    def test_the_zip_holds_only_the_app(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        assert "cp LICENSE" not in workflow
        assert "staging" not in workflow
        assert "--keepParent" in workflow

    def test_the_packaged_self_check_requires_both_files(self):
        selfcheck_source = bundle.resource_path("selfcheck.py").read_text(encoding="utf-8")
        assert '("licenses", "LICENSE")' in selfcheck_source
        assert '("licenses", "THIRD_PARTY_NOTICES.txt")' in selfcheck_source


class TestMakeNotices:
    @pytest.fixture
    def make_notices(self):
        spec = importlib.util.spec_from_file_location("make_notices", ROOT / "packaging" / "make_notices.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_runtime_section_names_python_and_the_native_libraries(self, make_notices):
        entries = make_notices.runtime_entries()
        labels = [label for label, _license, _texts in entries]
        assert labels[0].startswith("Python 3.")
        for library in ("OpenSSL", "SQLite", "zlib", "Expat", "libffi"):
            assert any(label.startswith(library) for label in labels)
        for _label, license_name, texts in entries:
            assert license_name and texts and all(texts)

    def test_the_whole_file_starts_with_what_the_smoke_test_looks_for(self, make_notices, tmp_path, monkeypatch):
        out = tmp_path / "notices.txt"
        monkeypatch.setattr(sys, "argv", ["make_notices.py", "--out", str(out)])
        monkeypatch.setattr(make_notices, "npm_entries", lambda: [])  # no npm needed to check the layout
        make_notices.main()
        text = out.read_text(encoding="utf-8")
        assert text.startswith("Lit Review includes")
        assert "Python runtime and the native libraries" in text
        assert "Python packages" in text
