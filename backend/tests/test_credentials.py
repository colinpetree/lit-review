import json
import threading

import pytest
from cryptography.fernet import Fernet

import credentials


def corrupt_copies():
    return sorted(p.name for p in credentials.CONFIG_DIR.glob("*.corrupt-*"))


class TestBasics:
    def test_a_saved_key_is_read_back(self):
        credentials.set_key("anthropic", "sk-1")
        assert credentials.get_key("anthropic") == "sk-1"
        assert credentials.has_key("anthropic")

    def test_a_key_that_was_never_saved_is_missing(self):
        assert credentials.get_key("openai") is None
        assert not credentials.has_key("openai")
        assert credentials.store_error() is False

    def test_saving_again_replaces_the_value_and_keeps_the_others(self):
        credentials.set_key("anthropic", "old")
        credentials.set_key("openai", "other")
        credentials.set_key("anthropic", "new")
        assert credentials.get_key("anthropic") == "new"
        assert credentials.get_key("openai") == "other"

    def test_delete_removes_only_that_key(self):
        credentials.set_key("anthropic", "a")
        credentials.set_key("openai", "b")
        credentials.delete_key("anthropic")
        assert not credentials.has_key("anthropic")
        assert credentials.get_key("openai") == "b"

    def test_deleting_a_key_that_is_not_saved_is_harmless(self):
        credentials.delete_key("anthropic")
        credentials.set_key("openai", "b")
        credentials.delete_key("anthropic")
        assert credentials.get_key("openai") == "b"

    def test_the_stored_file_does_not_contain_the_key_as_text(self):
        credentials.set_key("anthropic", "sk-plain-text-secret")
        assert b"sk-plain-text-secret" not in credentials.STORE_FILE.read_bytes()

    def test_an_environment_variable_is_the_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "from-env")
        assert credentials.get_key("openai") == "from-env"
        credentials.set_key("openai", "saved")
        assert credentials.get_key("openai") == "saved"

    def test_no_temp_files_are_left_behind(self):
        credentials.set_key("anthropic", "a")
        credentials.set_key("openai", "b")
        credentials.delete_key("anthropic")
        assert not list(credentials.CONFIG_DIR.glob("*.tmp"))


class TestUnreadableStore:
    @pytest.fixture
    def saved(self):
        credentials.set_key("anthropic", "keep-me")
        credentials.set_key("openai", "keep-me-too")

    def test_a_damaged_store_reads_as_no_keys_and_is_reported(self, saved):
        credentials.STORE_FILE.write_bytes(b"not a real store")
        assert credentials.get_key("anthropic") is None
        assert credentials.store_error() is True

    def test_saving_a_key_never_destroys_the_unreadable_store(self, saved):
        original = b"not a real store"
        credentials.STORE_FILE.write_bytes(original)

        credentials.set_key("gemini", "fresh")

        assert credentials.get_key("gemini") == "fresh"
        assert credentials.store_error() is False
        copies = [p for p in credentials.CONFIG_DIR.glob("credentials.enc.corrupt-*")]
        assert len(copies) == 1 and copies[0].read_bytes() == original

    def test_a_missing_key_file_is_reported_and_the_store_is_kept(self, saved):
        store_before = credentials.STORE_FILE.read_bytes()
        credentials.KEY_FILE.unlink()
        assert credentials.store_error() is True
        assert credentials.get_key("anthropic") is None
        # Reading must not invent a new key file that would make it worse.
        assert not credentials.KEY_FILE.exists()

        credentials.set_key("gemini", "fresh")

        assert credentials.get_key("gemini") == "fresh"
        assert any(p.read_bytes() == store_before for p in credentials.CONFIG_DIR.glob("credentials.enc.corrupt-*"))

    def test_the_original_key_file_is_kept_too(self, saved):
        old_key = credentials.KEY_FILE.read_bytes()
        credentials.STORE_FILE.write_bytes(b"junk")
        credentials.set_key("gemini", "fresh")
        assert any(p.read_bytes() == old_key for p in credentials.CONFIG_DIR.glob("credentials.key.corrupt-*"))
        assert credentials.KEY_FILE.read_bytes() != old_key

    def test_a_store_made_with_a_different_key_is_treated_as_unreadable(self, saved):
        credentials.KEY_FILE.write_bytes(Fernet.generate_key())
        assert credentials.store_error() is True
        assert credentials.get_key("anthropic") is None

    def test_a_damaged_key_file_is_treated_as_unreadable(self, saved):
        credentials.KEY_FILE.write_bytes(b"short")
        assert credentials.store_error() is True
        credentials.set_key("gemini", "fresh")
        assert credentials.get_key("gemini") == "fresh"
        assert corrupt_copies()

    def test_an_empty_key_file_with_no_store_does_not_break_saving(self):
        credentials.CONFIG_DIR.mkdir(parents=True)
        credentials.KEY_FILE.write_bytes(b"")
        credentials.set_key("anthropic", "a")
        assert credentials.get_key("anthropic") == "a"

    def test_a_store_that_is_not_a_dictionary_is_unreadable(self, saved):
        key = credentials.KEY_FILE.read_bytes()
        credentials.STORE_FILE.write_bytes(Fernet(key).encrypt(json.dumps(["a", "b"]).encode()))
        assert credentials.store_error() is True

    def test_a_store_that_is_not_json_is_unreadable(self, saved):
        key = credentials.KEY_FILE.read_bytes()
        credentials.STORE_FILE.write_bytes(Fernet(key).encrypt(b"\xff\xfe not json"))
        assert credentials.store_error() is True

    def test_deleting_with_an_unreadable_store_changes_nothing(self, saved):
        credentials.STORE_FILE.write_bytes(b"junk")
        credentials.delete_key("anthropic")
        assert credentials.STORE_FILE.read_bytes() == b"junk"
        assert not corrupt_copies()

    def test_the_environment_fallback_still_works_when_the_store_is_unreadable(self, saved, monkeypatch):
        credentials.STORE_FILE.write_bytes(b"junk")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        assert credentials.get_key("anthropic") == "from-env"

    def test_the_warning_is_logged_once_not_on_every_read(self, saved, caplog):
        credentials.STORE_FILE.write_bytes(b"junk")
        credentials._unreadable_logged = False
        with caplog.at_level("WARNING"):
            for _ in range(5):
                credentials.get_key("anthropic")
        assert caplog.text.count("could not be read") == 1


class TestAtomicWrites:
    def test_a_failed_write_leaves_the_old_store_intact(self, monkeypatch):
        credentials.set_key("anthropic", "original")
        before = credentials.STORE_FILE.read_bytes()

        def fail(src, dst):
            raise OSError("disk full")

        # A scoped patch: monkeypatch.undo() would also undo the autouse fixture's
        # redirect to the temp dir, and the next line would read the real files.
        with monkeypatch.context() as scoped:
            scoped.setattr(credentials.os, "replace", fail)
            with pytest.raises(OSError):
                credentials.set_key("openai", "new")

        assert str(credentials.STORE_FILE).startswith(str(credentials.CONFIG_DIR))
        assert credentials.STORE_FILE.read_bytes() == before
        assert credentials.get_key("anthropic") == "original"

    def test_the_key_file_is_never_overwritten(self):
        credentials.set_key("anthropic", "a")
        first = credentials.KEY_FILE.read_bytes()
        credentials.set_key("openai", "b")
        credentials.delete_key("openai")
        assert credentials.KEY_FILE.read_bytes() == first

    def test_creating_the_key_when_another_process_just_did_uses_theirs(self):
        credentials.CONFIG_DIR.mkdir(parents=True)
        theirs = Fernet.generate_key()
        credentials.KEY_FILE.write_bytes(theirs)
        assert credentials._create_key() == theirs
        assert credentials.KEY_FILE.read_bytes() == theirs

    @pytest.mark.skipif(not hasattr(__import__("os"), "geteuid"), reason="POSIX permissions only")
    def test_files_are_owner_only(self):
        import stat

        credentials.set_key("anthropic", "a")
        for path in (credentials.KEY_FILE, credentials.STORE_FILE):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestConcurrency:
    def test_parallel_saves_lose_no_keys(self):
        names = [f"provider{i}" for i in range(12)]
        errors = []

        def save(name):
            try:
                credentials.set_key(name, f"value-{name}")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=save, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert all(credentials.get_key(n) == f"value-{n}" for n in names)
        assert not corrupt_copies()


class TestStatusRoute:
    def test_the_status_reports_keys_and_no_store_error(self, client):
        credentials.set_key("anthropic", "a")
        data = client.get("/api/settings/api-key").get_json()
        assert data["anthropic"] is True
        assert data["openai"] is False
        assert data["store_error"] is False

    def test_the_status_reports_an_unreadable_store(self, client):
        credentials.set_key("anthropic", "a")
        credentials.STORE_FILE.write_bytes(b"junk")
        data = client.get("/api/settings/api-key").get_json()
        assert data["store_error"] is True
        assert data["anthropic"] is False

    def test_saving_through_the_route_recovers_and_keeps_a_copy(self, client):
        credentials.set_key("anthropic", "a")
        credentials.STORE_FILE.write_bytes(b"junk")
        response = client.post("/api/settings/api-key", json={"provider": "openai", "api_key": "b"})
        assert response.status_code == 200
        data = client.get("/api/settings/api-key").get_json()
        assert data["openai"] is True and data["store_error"] is False
        assert corrupt_copies()

    def test_the_status_never_contains_a_key_value(self, client):
        credentials.set_key("anthropic", "sk-super-secret")
        assert "sk-super-secret" not in client.get("/api/settings/api-key").get_data(as_text=True)
