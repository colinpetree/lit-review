"""The release-side scripts: the manifest builder (CI), the key maker and the signer (maintainer)."""

import base64
import datetime
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

import update_manifest as um

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(ROOT / "packaging"))
    spec.loader.exec_module(module)
    return module


make_manifest = load("make_manifest")
make_update_key = load("make_update_key")
sign_release = load("sign_release")

VERSION = "0.3.0"
NAMES = [f"Lit-Review-{VERSION}-Windows.zip", f"Lit-Review-{VERSION}-macOS-Apple-Silicon.zip", f"Lit-Review-{VERSION}-macOS-Intel.zip"]


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    for name in NAMES:
        with zipfile.ZipFile(folder / name, "w") as archive:
            archive.writestr("Lit Review/app", name * 10)
    (folder / f"Lit-Review-{VERSION}-macOS-Intel.dmg").write_bytes(b"dmg")  # must never be listed
    return folder


class TestMakeManifest:
    def test_lists_the_three_zips_and_never_the_dmg(self, out):
        raw = make_manifest.build(out, VERSION, today=datetime.date(2026, 10, 5))
        data = json.loads(raw)
        assert data["version"] == VERSION and data["tag"] == f"v{VERSION}" and data["released"] == "2026-10-05"
        assert [a["platform"] for a in data["assets"]] == ["windows", "macos-apple-silicon", "macos-intel"]
        assert all(a["name"].endswith(".zip") for a in data["assets"])
        assert "min_version" not in data

    def test_hashes_and_sizes_match_the_files(self, out):
        data = json.loads(make_manifest.build(out, VERSION))
        windows = data["assets"][0]
        path = out / windows["name"]
        assert windows["size"] == path.stat().st_size and windows["sha256"] == make_manifest.sha256_of(path)
        assert windows["unpacked_size"] > 0

    def test_the_result_is_accepted_by_the_apps_own_parser(self, out):
        manifest = um.parse(make_manifest.build(out, VERSION, notice="A note", min_version="0.2.0"))
        assert manifest.notice == "A note" and manifest.min_version == "0.2.0" and len(manifest.assets) == 3

    def test_the_output_is_stable(self, out):
        today = datetime.date(2026, 1, 1)
        assert make_manifest.build(out, VERSION, today=today) == make_manifest.build(out, VERSION, today=today)

    def test_a_missing_zip_stops_it(self, out):
        (out / NAMES[0]).unlink()
        with pytest.raises(SystemExit, match="expected 3 zips"):
            make_manifest.build(out, VERSION)

    def test_a_zip_for_another_version_stops_it(self, out):
        (out / NAMES[0]).rename(out / "Lit-Review-0.2.0-Windows.zip")
        with pytest.raises(SystemExit, match="is not a Lit-Review"):
            make_manifest.build(out, VERSION)

    def test_an_unrecognised_platform_stops_it(self, out):
        (out / NAMES[0]).rename(out / f"Lit-Review-{VERSION}-Linux.zip")
        with pytest.raises(SystemExit):
            make_manifest.build(out, VERSION)

    def test_the_command_writes_the_file(self, out, capsys):
        assert make_manifest.main(["--version", VERSION, "--dir", str(out)]) == 0
        assert (out / "update-manifest.json").is_file()


class TestMakeKey:
    def test_a_key_pair_signs_what_the_app_verifies(self):
        pem, public = make_update_key.new_pair(b"correct horse")
        raw = b"manifest"
        signature = sign_release.sign(pem, b"correct horse", raw)
        assert um.verify_signature(raw, signature, [public])

    def test_the_wrong_passphrase_cannot_sign(self):
        pem, _ = make_update_key.new_pair(b"right")
        with pytest.raises(ValueError):
            sign_release.sign(pem, b"wrong", b"x")

    def test_the_private_key_is_encrypted(self):
        pem, _ = make_update_key.new_pair(b"pw")
        assert b"ENCRYPTED" in pem

    def test_it_refuses_to_write_inside_the_repository_or_over_a_file(self, tmp_path):
        with pytest.raises(SystemExit, match="inside the repository"):
            make_update_key.check_destination(ROOT / "key.pem")
        existing = tmp_path / "k.pem"
        existing.write_text("x")
        with pytest.raises(SystemExit, match="already exists"):
            make_update_key.check_destination(existing)
        with pytest.raises(SystemExit, match="does not exist"):
            make_update_key.check_destination(tmp_path / "nope" / "k.pem")
        assert make_update_key.check_destination(tmp_path / "new.pem") == (tmp_path / "new.pem").resolve()

    def test_two_different_keys_come_out(self):
        assert make_update_key.new_pair(b"a")[1] != make_update_key.new_pair(b"a")[1]


class TestSignRelease:
    @pytest.fixture
    def release(self, out):
        raw = make_manifest.build(out, VERSION)
        (out / "update-manifest.json").write_bytes(raw)
        return out, raw

    def test_assets_that_match_pass(self, release):
        out, raw = release
        assert sign_release.check_assets(raw, out).version == VERSION

    def test_a_zip_changed_after_the_build_is_not_signed(self, release):
        out, raw = release
        (out / NAMES[1]).write_bytes(b"swapped")
        with pytest.raises(SystemExit, match="does not match"):
            sign_release.check_assets(raw, out)

    def test_a_missing_zip_is_refused(self, release):
        out, raw = release
        (out / NAMES[2]).unlink()
        with pytest.raises(SystemExit, match="not downloaded"):
            sign_release.check_assets(raw, out)

    def test_a_broken_manifest_is_refused(self, release):
        out, _ = release
        with pytest.raises(SystemExit, match="not usable"):
            sign_release.check_assets(b"{}", out)

    def test_amend_sets_min_version_and_notice(self, release):
        _, raw = release
        data = json.loads(sign_release.amend(raw, min_version="0.2.5", notice="Model retired."))
        assert data["min_version"] == "0.2.5" and data["notice"] == "Model retired."
        assert sign_release.amend(raw) == raw

    def test_amend_refuses_a_bad_version(self, release):
        _, raw = release
        with pytest.raises(SystemExit):
            sign_release.amend(raw, min_version="soon")

    def test_the_signed_result_verifies_end_to_end_and_a_tampered_floor_does_not(self, release, monkeypatch):
        _, raw = release
        pem, public = make_update_key.new_pair(b"pw")
        monkeypatch.setattr(um, "PUBLIC_KEYS", [public])
        amended = sign_release.amend(raw, min_version="0.2.0")
        signature = sign_release.sign(pem, b"pw", amended)
        manifest = um.load(amended, signature, "0.1.0")
        assert um.is_required(manifest, "0.1.0")
        with pytest.raises(um.ManifestError):
            um.load(amended.replace(b'"0.2.0"', b'"9.0.0"'), signature, "0.1.0")

    def test_a_key_the_app_does_not_trust_is_not_uploaded(self, release, monkeypatch):
        _, raw = release
        pem, _ = make_update_key.new_pair(b"pw")
        _, other_public = make_update_key.new_pair(b"x")
        monkeypatch.setattr(um, "PUBLIC_KEYS", [other_public])
        signature = sign_release.sign(pem, b"pw", raw)
        assert not um.verify_signature(raw, signature)

    def test_signing_needs_public_keys_in_the_app(self, monkeypatch):
        monkeypatch.setattr(um, "PUBLIC_KEYS", [])
        with pytest.raises(SystemExit, match="no PUBLIC_KEYS"):
            sign_release.sign_release("v0.3.0", "key.pem")

    def test_the_signature_file_is_base64_text(self):
        pem, _ = make_update_key.new_pair(b"pw")
        base64.b64decode(sign_release.sign(pem, b"pw", b"x"), validate=True)


class TestWorkflow:
    WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_the_manifest_is_made_and_attached_to_the_draft(self):
        assert "packaging/make_manifest.py" in self.WORKFLOW
        assert "out/update-manifest.json" in self.WORKFLOW

    def test_the_five_download_guard_still_counts_only_zips_and_dmgs(self):
        assert 'zips=(*.zip)' in self.WORKFLOW and 'dmgs=(*.dmg)' in self.WORKFLOW

    def test_a_tagged_build_without_public_keys_stops_before_the_app_is_built(self):
        guard = self.WORKFLOW.index("update_manifest.PUBLIC_KEYS")
        assert guard < self.WORKFLOW.index("pyinstaller backend/pyinstaller.spec")
        assert "refs/tags/" in self.WORKFLOW[guard - 300:guard]

    def test_keys_are_ignored_by_git(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "*.pem" in ignore and "update-signing*" in ignore
