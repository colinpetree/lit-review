"""The signed manifest: only bytes signed by a trusted key, naming a strictly newer version, are used."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_manifest as um

SHA = "a" * 64


def make_key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode()


def manifest_bytes(**overrides):
    data = {
        "format": 1,
        "version": "0.2.0",
        "tag": "v0.2.0",
        "released": "2026-10-05",
        "notice": "",
        "assets": [
            {"platform": "windows", "name": "Lit-Review-0.2.0-windows.zip", "size": 100, "unpacked_size": 300, "sha256": SHA},
        ],
    }
    data.update(overrides)
    return json.dumps({k: v for k, v in data.items() if v is not None}).encode()


def sign(private, raw, prefix=um.SIGNATURE_PREFIX):
    return base64.b64encode(private.sign(prefix + raw)).decode()


@pytest.fixture
def key(monkeypatch):
    private, public = make_key()
    monkeypatch.setattr(um, "PUBLIC_KEYS", [public])
    return private


class TestSignature:
    def test_a_good_signature_verifies(self, key):
        raw = manifest_bytes()
        assert um.verify_signature(raw, sign(key, raw))

    def test_changed_bytes_fail(self, key):
        raw = manifest_bytes()
        assert not um.verify_signature(raw + b" ", sign(key, raw))

    def test_another_key_fails(self, key):
        other, _ = make_key()
        raw = manifest_bytes()
        assert not um.verify_signature(raw, sign(other, raw))

    def test_a_signature_without_the_domain_prefix_is_rejected(self, key):
        raw = manifest_bytes()
        assert not um.verify_signature(raw, sign(key, raw, prefix=b""))

    def test_garbage_signature_is_rejected_not_raised(self, key):
        raw = manifest_bytes()
        for bad in ("", "not base64!!", "AAAA", base64.b64encode(b"x" * 64).decode()):
            assert not um.verify_signature(raw, bad)

    def test_the_spare_key_also_works(self, monkeypatch):
        spare, spare_public = make_key()
        _, active_public = make_key()
        monkeypatch.setattr(um, "PUBLIC_KEYS", [active_public, spare_public])
        raw = manifest_bytes()
        assert um.verify_signature(raw, sign(spare, raw))

    def test_no_keys_means_nothing_verifies(self, monkeypatch):
        private, _ = make_key()
        monkeypatch.setattr(um, "PUBLIC_KEYS", [])
        raw = manifest_bytes()
        assert not um.verify_signature(raw, sign(private, raw))

    def test_the_test_key_is_ignored_without_the_testing_switch(self, monkeypatch):
        private, public = make_key()
        monkeypatch.setattr(um, "PUBLIC_KEYS", [])
        monkeypatch.setenv("LIT_REVIEW_UPDATE_PUBKEY", public)
        monkeypatch.delenv("LIT_REVIEW_TESTING", raising=False)
        raw = manifest_bytes()
        assert not um.verify_signature(raw, sign(private, raw))

    def test_the_test_key_is_used_with_the_testing_switch(self, monkeypatch):
        private, public = make_key()
        monkeypatch.setattr(um, "PUBLIC_KEYS", [])
        monkeypatch.setenv("LIT_REVIEW_UPDATE_PUBKEY", public)
        monkeypatch.setenv("LIT_REVIEW_TESTING", "1")
        raw = manifest_bytes()
        assert um.verify_signature(raw, sign(private, raw))


class TestLoad:
    def test_a_signed_newer_release_loads(self, key):
        raw = manifest_bytes()
        manifest = um.load(raw, sign(key, raw), "0.1.0")
        assert manifest.version == "0.2.0"
        assert um.asset_for(manifest, "windows").name == "Lit-Review-0.2.0-windows.zip"
        assert um.asset_for(manifest, "macos-intel") is None

    def test_unsigned_is_refused(self, key):
        raw = manifest_bytes()
        with pytest.raises(um.ManifestError, match="signature"):
            um.load(raw, "", "0.1.0")

    @pytest.mark.parametrize("running", ["0.2.0", "0.3.0"])
    def test_same_or_older_release_is_refused(self, key, running):
        raw = manifest_bytes()
        with pytest.raises(um.ManifestError, match="not newer"):
            um.load(raw, sign(key, raw), running)

    def test_a_development_build_is_never_offered_anything(self, key):
        raw = manifest_bytes()
        with pytest.raises(um.ManifestError, match="development"):
            um.load(raw, sign(key, raw), "0.0.0-dev")

    def test_tag_must_match_version(self, key):
        raw = manifest_bytes(tag="v0.1.9")
        with pytest.raises(um.ManifestError, match="tag"):
            um.load(raw, sign(key, raw), "0.1.0")

    @pytest.mark.parametrize(
        "change",
        [
            {"format": 2},
            {"format": True},
            {"version": "0.2"},
            {"version": "v0.2.0"},
            {"assets": []},
            {"assets": "x"},
            {"min_version": "soon"},
            {"notice": 5},
        ],
    )
    def test_malformed_manifests_are_refused(self, key, change):
        raw = manifest_bytes(**change)
        with pytest.raises(um.ManifestError):
            um.load(raw, sign(key, raw), "0.1.0")

    @pytest.mark.parametrize(
        "name",
        ["../x.zip", "a/b.zip", "a\\b.zip", "x.exe", ".zip", "C:evil.zip", "x.zip\n", "", "a" * 200 + ".zip"],
    )
    def test_unsafe_file_names_are_refused(self, key, name):
        asset = {"platform": "windows", "name": name, "size": 1, "unpacked_size": 1, "sha256": SHA}
        raw = manifest_bytes(assets=[asset])
        with pytest.raises(um.ManifestError):
            um.load(raw, sign(key, raw), "0.1.0")

    @pytest.mark.parametrize(
        "asset",
        [
            {"platform": "linux", "name": "a.zip", "size": 1, "unpacked_size": 1, "sha256": SHA},
            {"platform": "windows", "name": "a.zip", "size": 0, "unpacked_size": 1, "sha256": SHA},
            {"platform": "windows", "name": "a.zip", "size": True, "unpacked_size": 1, "sha256": SHA},
            {"platform": "windows", "name": "a.zip", "size": 1, "unpacked_size": -1, "sha256": SHA},
            {"platform": "windows", "name": "a.zip", "size": 1, "unpacked_size": 1, "sha256": "A" * 64},
            {"platform": "windows", "name": "a.zip", "size": 1, "unpacked_size": 1, "sha256": "abc"},
        ],
    )
    def test_bad_asset_fields_are_refused(self, key, asset):
        raw = manifest_bytes(assets=[asset])
        with pytest.raises(um.ManifestError):
            um.load(raw, sign(key, raw), "0.1.0")

    def test_a_platform_listed_twice_is_refused(self, key):
        asset = {"platform": "windows", "name": "a.zip", "size": 1, "unpacked_size": 1, "sha256": SHA}
        raw = manifest_bytes(assets=[asset, asset])
        with pytest.raises(um.ManifestError, match="twice"):
            um.load(raw, sign(key, raw), "0.1.0")

    def test_not_json_is_refused(self, key):
        raw = b"{nope"
        with pytest.raises(um.ManifestError):
            um.load(raw, sign(key, raw), "0.1.0")


class TestRequired:
    def test_running_below_min_version_is_required(self, key):
        raw = manifest_bytes(min_version="0.1.1")
        manifest = um.load(raw, sign(key, raw), "0.1.0")
        assert um.is_required(manifest, "0.1.0")

    def test_a_skipped_release_is_still_required(self, key):
        # Running 0.1.0, latest is 0.1.2 and its floor is 0.1.1: the floor applies to 0.1.0.
        raw = manifest_bytes(version="0.1.2", tag="v0.1.2", min_version="0.1.1")
        manifest = um.load(raw, sign(key, raw), "0.1.0")
        assert um.is_required(manifest, "0.1.0")

    def test_at_or_above_the_floor_is_not_required(self, key):
        raw = manifest_bytes(min_version="0.1.1")
        manifest = um.load(raw, sign(key, raw), "0.1.1")
        assert not um.is_required(manifest, "0.1.1")
        assert not um.is_required(manifest, "0.1.5")

    def test_no_floor_means_not_required(self, key):
        raw = manifest_bytes()
        assert not um.is_required(um.load(raw, sign(key, raw), "0.1.0"), "0.1.0")

    def test_a_changed_floor_breaks_the_signature(self, key):
        raw = manifest_bytes(min_version="0.1.1")
        signature = sign(key, raw)
        tampered = raw.replace(b"0.1.1", b"9.9.9")
        with pytest.raises(um.ManifestError, match="signature"):
            um.load(tampered, signature, "0.1.0")


class TestPlatform:
    @pytest.mark.parametrize(
        "plat, machine, expected",
        [
            ("win32", "AMD64", "windows"),
            ("darwin", "arm64", "macos-apple-silicon"),
            ("darwin", "x86_64", "macos-intel"),
            ("linux", "x86_64", None),
        ],
    )
    def test_platform_key(self, plat, machine, expected):
        assert um.platform_key(machine=machine, plat=plat) == expected
