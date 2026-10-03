"""The per-user secret and the running-copy record (access.py)."""

import json
import os
import stat

import pytest

import access

WINDOWS = os.name == "nt"


class TestToken:
    def test_a_token_is_created_on_first_use(self, tmp_path):
        token = access.load_or_create_token(tmp_path)
        assert isinstance(token, str)
        assert len(token) >= access.MIN_TOKEN_LENGTH
        assert (tmp_path / access.TOKEN_FILE).read_text(encoding="utf-8").strip() == token

    def test_it_is_long_random_and_safe_in_a_url(self, tmp_path):
        token = access.load_or_create_token(tmp_path)
        assert len(token) >= 43  # 32 random bytes
        assert set(token) <= access._URLSAFE

    def test_it_is_kept_across_restarts(self, tmp_path):
        assert access.load_or_create_token(tmp_path) == access.load_or_create_token(tmp_path)

    def test_each_folder_gets_its_own(self, tmp_path):
        assert access.load_or_create_token(tmp_path / "a") != access.load_or_create_token(tmp_path / "b")

    def test_the_folder_is_created_if_missing(self, tmp_path):
        access.load_or_create_token(tmp_path / "deep" / "er")
        assert (tmp_path / "deep" / "er" / access.TOKEN_FILE).is_file()

    @pytest.mark.parametrize(
        "damaged",
        ["", "   \n", "short", "x" * 31, "has spaces in it " * 4, "naughty/../path" * 4, "ünïcode" * 10, "\x00" * 40],
    )
    def test_a_missing_or_damaged_file_is_replaced_with_a_new_secret(self, tmp_path, damaged):
        (tmp_path / access.TOKEN_FILE).write_text(damaged, encoding="utf-8")
        token = access.load_or_create_token(tmp_path)
        assert token != damaged.strip()
        assert len(token) >= access.MIN_TOKEN_LENGTH
        assert access.load_or_create_token(tmp_path) == token  # and it sticks

    @pytest.mark.parametrize(
        "damaged",
        [
            pytest.param(b"\xff\xfe\x00\x80\x81\x82" * 10, id="invalid-utf8"),
            pytest.param("A".encode("utf-16"), id="utf16-with-bom"),
            pytest.param(("x" * 43).encode("utf-16-le"), id="utf16-no-bom"),
            pytest.param(b"\x00" * 64, id="nul-bytes"),
            pytest.param(b"\xef\xbb\xbf" + b"A" * 43 + b"\xff", id="bom-and-a-stray-byte"),
            pytest.param(bytes(range(256)), id="every-byte-value"),
        ],
    )
    def test_a_file_that_is_not_text_is_replaced_not_a_crash(self, tmp_path, damaged):
        """A damaged or oddly saved file must never stop the app from starting."""
        (tmp_path / access.TOKEN_FILE).write_bytes(damaged)
        token = access.load_or_create_token(tmp_path)
        assert len(token) >= access.MIN_TOKEN_LENGTH and set(token) <= access._URLSAFE
        assert access.load_or_create_token(tmp_path) == token

    def test_a_trailing_newline_in_the_file_is_ignored(self, tmp_path):
        token = "A" * 43
        (tmp_path / access.TOKEN_FILE).write_text(token + "\r\n", encoding="utf-8")
        assert access.load_or_create_token(tmp_path) == token

    def test_two_secrets_are_never_equal(self, tmp_path):
        assert len({access.load_or_create_token(tmp_path / str(i)) for i in range(25)}) == 25

    def test_a_good_secret_is_never_rewritten(self, tmp_path):
        access.load_or_create_token(tmp_path)
        before = (tmp_path / access.TOKEN_FILE).stat().st_mtime_ns
        access.load_or_create_token(tmp_path)
        assert (tmp_path / access.TOKEN_FILE).stat().st_mtime_ns == before


class TestWritesAreAtomic:
    def test_no_temporary_files_are_left_behind(self, tmp_path):
        access.load_or_create_token(tmp_path)
        access.write_instance(tmp_path, 5175, "a")
        access.write_instance(tmp_path, 5176, "b")
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([access.INSTANCE_FILE, access.TOKEN_FILE])

    def test_a_failed_write_leaves_the_old_secret_untouched_and_no_debris(self, tmp_path, monkeypatch):
        (tmp_path / access.TOKEN_FILE).write_text("damaged", encoding="utf-8")  # forces a rewrite

        def fail(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(access.os, "replace", fail)
        with pytest.raises(OSError, match="disk full"):
            access.load_or_create_token(tmp_path)
        monkeypatch.undo()

        assert (tmp_path / access.TOKEN_FILE).read_text(encoding="utf-8") == "damaged"  # not half-written
        assert [p.name for p in tmp_path.iterdir()] == [access.TOKEN_FILE]  # and the temp file was cleaned up

    def test_a_failed_record_write_leaves_the_old_record(self, tmp_path, monkeypatch):
        access.write_instance(tmp_path, 5175, "old")

        def fail(src, dst):
            raise OSError("disk full")

        with monkeypatch.context() as scoped:
            scoped.setattr(access.os, "replace", fail)
            with pytest.raises(OSError):
                access.write_instance(tmp_path, 5176, "new")

        assert access.read_instance(tmp_path) == {"port": 5175, "id": "old"}
        assert [p.name for p in tmp_path.iterdir()] == [access.INSTANCE_FILE]

    @pytest.mark.skipif(WINDOWS, reason="POSIX modes")
    def test_on_mac_and_linux_the_files_are_readable_by_their_owner_only(self, tmp_path):
        access.load_or_create_token(tmp_path)
        access.write_instance(tmp_path, 5175, "x")
        for name in (access.TOKEN_FILE, access.INSTANCE_FILE):
            assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


class TestInstanceRecord:
    def test_it_round_trips(self, tmp_path):
        access.write_instance(tmp_path, 5176, "abc123")
        assert access.read_instance(tmp_path) == {"port": 5176, "id": "abc123"}

    def test_a_missing_record_is_none(self, tmp_path):
        assert access.read_instance(tmp_path) is None

    @pytest.mark.parametrize(
        "content",
        [
            "",
            "not json",
            "[]",
            "null",
            "42",
            '"text"',
            "{}",
            '{"port": 5175}',
            '{"id": "x"}',
            '{"port": "5175", "id": "x"}',
            '{"port": 5175.5, "id": "x"}',
            '{"port": true, "id": "x"}',
            '{"port": 0, "id": "x"}',
            '{"port": 70000, "id": "x"}',
            '{"port": -1, "id": "x"}',
            '{"port": 5175, "id": ""}',
            '{"port": 5175, "id": 7}',
            '{"port": 5175, "id": null}',
        ],
    )
    def test_a_damaged_or_odd_record_is_none(self, tmp_path, content):
        (tmp_path / access.INSTANCE_FILE).write_text(content, encoding="utf-8")
        assert access.read_instance(tmp_path) is None

    def test_a_record_that_is_not_text_is_just_no_record(self, tmp_path):
        (tmp_path / access.INSTANCE_FILE).write_bytes(b"\xff\xfe\x00\x80")
        assert access.read_instance(tmp_path) is None

    def test_clearing_removes_only_its_own_record(self, tmp_path):
        access.write_instance(tmp_path, 5175, "old")
        access.write_instance(tmp_path, 5176, "new")  # a newer copy took over the file
        access.clear_instance(tmp_path, "old")
        assert access.read_instance(tmp_path) == {"port": 5176, "id": "new"}
        access.clear_instance(tmp_path, "new")
        assert access.read_instance(tmp_path) is None

    def test_clearing_when_there_is_nothing_is_harmless(self, tmp_path):
        access.clear_instance(tmp_path, "whatever")
        access.clear_instance(tmp_path / "no" / "such" / "folder", "whatever")

    def test_writing_again_replaces_it(self, tmp_path):
        for port in (5175, 5176, 5177):
            access.write_instance(tmp_path, port, f"id{port}")
        assert access.read_instance(tmp_path)["port"] == 5177

    def test_it_is_plain_json(self, tmp_path):
        access.write_instance(tmp_path, 5175, "x")
        assert json.loads((tmp_path / access.INSTANCE_FILE).read_text(encoding="utf-8")) == {"port": 5175, "id": "x"}


class TestLaunchUrl:
    def test_with_a_secret_it_is_the_private_link_with_the_secret_in_the_fragment(self):
        assert access.launch_url(5175, "SECRET") == "http://127.0.0.1:5175/#token=SECRET"

    def test_the_secret_is_after_the_hash_so_a_browser_never_sends_it_to_a_server(self):
        from urllib.parse import urlparse

        parsed = urlparse(access.launch_url(5175, "SECRET"))
        assert "SECRET" not in parsed.path + parsed.query  # what actually goes over the wire
        assert parsed.fragment == "token=SECRET"

    def test_without_one_it_is_the_plain_address(self):
        assert access.launch_url(5176) == "http://127.0.0.1:5176"
        assert access.launch_url(5176, None) == "http://127.0.0.1:5176"
        assert access.launch_url(5176, "") == "http://127.0.0.1:5176"

    def test_a_real_token_survives_being_put_in_a_url(self, tmp_path):
        from urllib.parse import parse_qs, urlparse

        token = access.load_or_create_token(tmp_path)
        assert parse_qs(urlparse(access.launch_url(5175, token)).fragment)["token"] == [token]


class TestNothingLeftOfThePermissionHelpers:
    """The app no longer runs helper programs or touches file permissions on Windows: the
    profile folder is the boundary, so there is nothing there to go wrong at startup."""

    def test_no_subprocess_is_used_at_all(self):
        import inspect

        source = inspect.getsource(access)
        for word in ("subprocess", "icacls", "whoami", "chmod"):
            assert word not in source

    def test_creating_the_secret_starts_no_other_program(self, tmp_path, monkeypatch):
        import subprocess

        def forbidden(*args, **kwargs):
            raise AssertionError("a program was started")

        monkeypatch.setattr(subprocess, "run", forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        access.load_or_create_token(tmp_path)
        access.write_instance(tmp_path, 5175, "x")
