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


class TestSignInCI:
    """sign_release.py as the Publish release workflow's `sign` job runs it (--ci --publish)."""

    @pytest.fixture
    def draft(self, out, monkeypatch):
        """A fake draft release: `gh release download` copies `out` (zips, manifest, sums) into the
        work folder; every gh call is recorded."""
        raw = make_manifest.build(out, VERSION)
        (out / "update-manifest.json").write_bytes(raw)
        sums = "".join(f"{make_manifest.sha256_of(out / name)}  {name}\n" for name in NAMES)
        (out / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
        pem, public = make_update_key.new_pair(b"pw")
        monkeypatch.setattr(um, "PUBLIC_KEYS", [public])
        calls = []

        def fake_gh(*args):
            calls.append(args)
            if args[:2] == ("release", "download"):
                work = Path(args[args.index("--dir") + 1])
                for f in out.iterdir():
                    if f.suffix in (".zip", ".json", ".txt"):
                        (work / f.name).write_bytes(f.read_bytes())

        monkeypatch.setattr(sign_release, "gh", fake_gh)
        monkeypatch.setattr(sign_release, "VERIFY_WAIT_SECONDS", 0)
        return out, pem, calls

    def test_it_signs_publishes_and_verifies(self, draft, monkeypatch):
        out, pem, calls = draft
        verified = []
        monkeypatch.setattr(sign_release, "verify_published", lambda tag: verified.append(tag))
        sign_release.sign_release(f"v{VERSION}", pem=pem, passphrase=b"pw", publish=True)
        upload = next(c for c in calls if c[:2] == ("release", "upload"))
        assert upload[2] == f"v{VERSION}"
        assert ("release", "edit", f"v{VERSION}", "--repo", sign_release.REPO, "--draft=false", "--latest") in calls
        assert calls.index(upload) < calls.index(next(c for c in calls if c[:2] == ("release", "edit")))  # signed, then published
        assert verified == [f"v{VERSION}"]

    def test_a_zip_that_differs_from_the_builds_sums_is_never_signed(self, draft):
        out, pem, calls = draft
        sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
        (out / "SHA256SUMS.txt").write_text(sums.replace(sums[:8], "00000000", 1), encoding="utf-8")
        with pytest.raises(SystemExit, match="SHA256SUMS"):
            sign_release.sign_release(f"v{VERSION}", pem=pem, passphrase=b"pw", publish=True)
        assert not any(c[:2] in (("release", "upload"), ("release", "edit")) for c in calls)

    def test_a_draft_without_sums_is_never_signed(self, draft):
        out, pem, calls = draft
        (out / "SHA256SUMS.txt").unlink()
        with pytest.raises(SystemExit, match="no SHA256SUMS"):
            sign_release.sign_release(f"v{VERSION}", pem=pem, passphrase=b"pw", publish=True)
        assert not any(c[:2] == ("release", "upload") for c in calls)

    def test_a_key_the_app_does_not_trust_is_never_uploaded_or_published(self, draft):
        _, _, calls = draft
        other, _ = make_update_key.new_pair(b"pw")
        with pytest.raises(SystemExit, match="not one of the public keys"):
            sign_release.sign_release(f"v{VERSION}", pem=other, passphrase=b"pw", publish=True)
        assert not any(c[:2] in (("release", "upload"), ("release", "edit")) for c in calls)

    def test_a_published_release_that_does_not_verify_fails_loudly(self, draft, monkeypatch):
        _, pem, _ = draft

        def broken(tag):
            raise SystemExit("does NOT verify")

        monkeypatch.setattr(sign_release, "verify_published", broken)
        with pytest.raises(SystemExit, match="is PUBLISHED but does not verify"):
            sign_release.sign_release(f"v{VERSION}", pem=pem, passphrase=b"pw", publish=True)

    def test_empty_secrets_stop_plainly(self):
        for env in ({}, {"UPDATE_SIGNING_KEY": "x"}, {"UPDATE_SIGNING_KEY": "  ", "UPDATE_SIGNING_PASSPHRASE": "p"}):
            with pytest.raises(SystemExit, match="release` environment"):
                sign_release.key_from_environment(env)
        assert sign_release.key_from_environment({"UPDATE_SIGNING_KEY": "k", "UPDATE_SIGNING_PASSPHRASE": "p"}) == (b"k", b"p")


def workflow(name):
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def job(text, name):
    """One job's text from a workflow file (up to the next top-level job)."""
    start = text.index(f"\n  {name}:")
    rest = text[start + 1 :]
    following = [rest.find(f"\n  {line.split(':')[0].strip()}:") for line in rest.splitlines()[1:] if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":")]
    following = [i for i in following if i > 0]
    return rest[: min(following)] if following else rest


class TestWorkflow:
    BUILD = workflow("build-test.yml")
    CI = workflow("ci.yml")
    PUBLISH = workflow("release.yml")

    def test_the_manifest_is_made_and_attached_to_the_release_draft(self):
        publish = job(self.PUBLISH, "publish")
        assert "packaging/make_manifest.py" in publish
        assert "out/update-manifest.json" in publish
        assert "update-manifest" not in job(self.CI, "draft")  # a Candidate never carries one

    def test_the_five_download_guard_still_counts_only_zips_and_dmgs(self):
        assert 'zips=(*.zip)' in self.BUILD and 'dmgs=(*.dmg)' in self.BUILD

    def test_a_release_build_without_public_keys_stops_before_the_app_is_built(self):
        guard = self.BUILD.index("update_manifest.PUBLIC_KEYS")
        assert guard < self.BUILD.index("pyinstaller backend/pyinstaller.spec")
        assert r"^[0-9]+\.[0-9]+\.[0-9]+$" in self.BUILD[guard - 300:guard]  # every X.Y.Z build is one that may ship

    def test_only_the_sign_job_can_read_the_key_and_it_waits_for_approval(self):
        assert self.PUBLISH.count("secrets.UPDATE_SIGNING_KEY") == 1
        sign = job(self.PUBLISH, "sign")
        assert "environment: release" in sign and "secrets.UPDATE_SIGNING_KEY" in sign
        assert "--require-hashes" in sign and "packaging/requirements-sign.txt" in sign
        assert "npm" not in sign and "pip install -r backend" not in sign
        for name in ("ci.yml", "build-test.yml", "codeql.yml", "dependency-audit.yml"):
            assert "secrets." not in workflow(name), name

    def test_the_signing_requirements_are_hash_pinned(self):
        lines = (ROOT / "packaging" / "requirements-sign.txt").read_text(encoding="utf-8").splitlines()
        pins = [line for line in lines if line and not line.startswith((" ", "#"))]
        assert pins and all("==" in line for line in pins)
        assert any(line.startswith("cryptography==") for line in pins)
        assert sum("--hash=sha256:" in line for line in lines) >= len(pins)

    def test_the_approval_job_is_outside_the_publish_queue(self):
        # A run waiting days for Approve must not hold up the next Publish or a test build.
        assert "concurrency" not in job(self.PUBLISH, "sign")
        assert "group: publish" in job(self.PUBLISH, "plan") and "group: publish" in job(self.PUBLISH, "publish")
        assert "group: publish" not in self.CI

    def test_nothing_a_person_types_reaches_a_shell_directly(self):
        # Branch names and the Publish inputs go through env:, never ${{ }} inside run: (script injection).
        for name in ("ci.yml", "build-test.yml", "release.yml", "codeql.yml", "dependency-audit.yml"):
            text = workflow(name)
            for block in text.split("run: |")[1:]:
                body = []
                for line in block.splitlines()[1:]:
                    if line.strip() and not line.startswith(" " * 10):
                        break
                    body.append(line)
                script = "\n".join(body)
                for risky in ("inputs.", "github.head_ref", "github.event.", "github.ref_name"):
                    assert "${{ " + risky not in script, f"{name}: {risky} used inside a run block"

    def test_main_builds_are_the_next_patch_and_rehearse_the_update(self):
        prepare = job(self.CI, "prepare")
        assert 'version="$major.$minor.$((patch + 1))"' in prepare
        assert "rehearse_update: ${{ needs.prepare.outputs.release == 'true' }}" in self.CI
        assert "packaging/update_rehearsal.py" in self.BUILD and "packaging/upgrade_test.py" in self.BUILD

    def test_jobs_after_a_sometimes_skipped_build_say_when_they_run(self):
        # For a patch `build` is skipped. GitHub's default condition skips a job when any job
        # earlier in its chain was skipped, even if the job just before it ran (actions/runner#491),
        # so every job downstream of `build` needs an explicit `if:` or it never runs on a patch.
        for name in ("publish", "sign", "release-claim"):
            body = job(self.PUBLISH, name)
            condition = next((line for line in body.splitlines() if line.strip().startswith("if:")), "")
            assert "always()" in condition or "!cancelled()" in condition, f"{name} has no explicit run condition"
        sign = next(line for line in job(self.PUBLISH, "sign").splitlines() if line.strip().startswith("if:"))
        assert "needs.publish.result == 'success'" in sign

    def test_the_build_only_ever_checks_out_the_runs_own_commit(self):
        # A commit passed in to the build (with its caches) is what CodeQL calls cache poisoning:
        # the build takes no `ref`, and a minor/major Publish rebuilds the commit it was started on.
        assert "inputs.ref" not in self.BUILD and "\n      ref:" not in self.BUILD
        assert "ref:" not in job(self.PUBLISH, "build")
        assert '[ "$sha" = "$GITHUB_SHA" ]' in job(self.PUBLISH, "plan")

    def test_a_patch_publish_never_rebuilds(self):
        assert "if: needs.plan.outputs.rebuild == 'true'" in job(self.PUBLISH, "build")
        assert "rebuild=false" in job(self.PUBLISH, "plan")

    def test_the_draft_never_waits_on_a_pull_request_only_job(self):
        needs = next(line for line in job(self.CI, "draft").splitlines() if "needs:" in line)
        assert "dependency-review" not in needs

    def test_versions_come_from_published_releases_not_tags(self):
        script = (ROOT / ".github" / "scripts" / "previous-release.sh").read_text(encoding="utf-8")
        assert "--exclude-drafts --exclude-pre-releases" in script and "merge-base --is-ancestor" in script
        assert ".github/scripts/previous-release.sh" in self.CI and ".github/scripts/previous-release.sh" in self.PUBLISH
        assert "tags:" not in self.PUBLISH.split("\njobs:")[0]  # a pushed tag starts nothing

    def test_keys_are_ignored_by_git(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "*.pem" in ignore and "update-signing*" in ignore
