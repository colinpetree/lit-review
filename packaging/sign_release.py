"""Sign a draft release's update manifest, and optionally publish it.

Normally GitHub runs this, in the Publish release workflow's `sign` job, once you Approve it:

    python packaging/sign_release.py v0.1.0 --ci --publish

with the key and its passphrase taken from the `release` environment's two secrets
(UPDATE_SIGNING_KEY, UPDATE_SIGNING_PASSPHRASE). By hand it is the fallback (GitHub Actions
down, or signing with the offline spare key to retire a leaked one):

    python packaging/sign_release.py v0.1.0 --key D:\\keys\\lit-review-active.pem [--publish]
    python packaging/sign_release.py v0.1.0 --key ... --min-version 0.1.0 --notice "Model X was retired."
    python packaging/sign_release.py --verify v0.1.0

Needs the GitHub CLI (`gh`), signed in (in CI, GH_TOKEN). It downloads the draft's zips and
manifest, re-hashes every zip against the manifest and against the build's SHA256SUMS.txt (so a
zip swapped after the build cannot be signed by accident), signs, checks the signature against
the public keys built into the app, and uploads `update-manifest.json.sig`. With --publish it
then publishes the draft and checks it the way the app will (as --verify does).

`--min-version` and `--notice` change the manifest (it is rewritten, then signed): a version
older than `--min-version` is treated as one that must update. Use it only for a version that
really can no longer work, and only after trying the update path on a real machine. (Publish
release has a `required_update` checkbox, which sets the floor to the version it publishes, and
a `notice` input; it writes both into the manifest it makes.)

`--verify TAG` downloads a PUBLISHED release's manifest and signature the way the app does and
checks them against the embedded keys.
"""

import argparse
import base64
import getpass
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import update_manifest as um  # noqa: E402
from make_manifest import MANIFEST_NAME, sha256_of  # noqa: E402
from updates import REPO  # noqa: E402

SIGNATURE_NAME = MANIFEST_NAME + ".sig"
SUMS_NAME = "SHA256SUMS.txt"
VERIFY_ATTEMPTS = 6  # a just-published release's files can take a moment to be served
VERIFY_WAIT_SECONDS = 10


def check_assets(raw, directory):
    """The parsed manifest, after confirming every zip in `directory` has the size and SHA-256 it lists."""
    try:
        manifest = um.parse(raw)
    except um.ManifestError as exc:
        raise SystemExit(f"the manifest is not usable: {exc}")
    for asset in manifest.assets:
        path = Path(directory) / asset.name
        if not path.is_file():
            raise SystemExit(f"{asset.name} is listed in the manifest but was not downloaded")
        if path.stat().st_size != asset.size or sha256_of(path) != asset.sha256:
            raise SystemExit(f"{asset.name} does not match the manifest (it changed after the build): not signing")
    return manifest


def check_sums(directory):
    """Every zip in `directory` must match the SHA256SUMS.txt the build wrote beside it: a second
    record of the tested files, made by the build, before Publish release made the manifest."""
    sums = Path(directory) / SUMS_NAME
    if not sums.is_file():
        raise SystemExit(f"the draft has no {SUMS_NAME}: not signing")
    listed = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            listed[parts[1].lstrip("*")] = parts[0]
    zips = sorted(Path(directory).glob("*.zip"))
    if not zips:
        raise SystemExit("no zips were downloaded: not signing")
    for path in zips:
        if listed.get(path.name) != sha256_of(path):
            raise SystemExit(f"{path.name} does not match {SUMS_NAME} (it changed after the build): not signing")


def amend(raw, min_version=None, notice=None):
    """The manifest bytes with `min_version` and/or `notice` changed (or `raw` itself if neither)."""
    if min_version is None and notice is None:
        return raw
    data = json.loads(raw)
    if min_version is not None:
        if um.parse_version(min_version) is None:
            raise SystemExit(f"{min_version!r} is not a version number")
        data["min_version"] = min_version
    if notice is not None:
        data["notice"] = notice
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sign(pem, passphrase, raw):
    """Base64 Ed25519 signature over the domain-prefixed manifest bytes."""
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(pem, password=passphrase)
    return base64.b64encode(key.sign(um.SIGNATURE_PREFIX + raw))


def key_from_environment(env=None):
    """(pem bytes, passphrase bytes) from UPDATE_SIGNING_KEY and UPDATE_SIGNING_PASSPHRASE, the two
    secrets of the GitHub `release` environment. Stops plainly if either is missing."""
    env = os.environ if env is None else env
    pem, passphrase = env.get("UPDATE_SIGNING_KEY", ""), env.get("UPDATE_SIGNING_PASSPHRASE", "")
    if not pem.strip() or not passphrase:
        raise SystemExit(
            "UPDATE_SIGNING_KEY or UPDATE_SIGNING_PASSPHRASE is empty: set up the `release` environment "
            "and its two secrets (RELEASING.md, One-time setup)"
        )
    return pem.encode("utf-8"), passphrase.encode("utf-8")


def gh(*args):
    return subprocess.run(["gh", *args], check=True)


def sign_release(tag, key_path=None, min_version=None, notice=None, *, pem=None, passphrase=None, publish=False):
    """Sign the draft release `tag`: by hand with a key file (asking for its passphrase), or in CI with
    `pem` and `passphrase` given. With `publish`, then publish it and check it as the app will."""
    if not um.PUBLIC_KEYS:
        raise SystemExit("backend/update_manifest.py has no PUBLIC_KEYS yet: run make_update_key.py and paste them in first")
    with tempfile.TemporaryDirectory() as work:
        gh("release", "download", tag, "--repo", REPO, "--dir", work,
           "--pattern", "*.zip", "--pattern", MANIFEST_NAME, "--pattern", SUMS_NAME)
        raw = (Path(work) / MANIFEST_NAME).read_bytes()
        manifest = check_assets(raw, work)
        check_sums(work)
        if manifest.tag != tag:
            raise SystemExit(f"the manifest is for {manifest.tag}, not {tag}")
        amended = amend(raw, min_version, notice)
        if amended != raw:
            check_assets(amended, work)
        if pem is None:
            pem = Path(key_path).read_bytes()
        if passphrase is None:
            passphrase = getpass.getpass("Key passphrase: ").encode()
        signature = sign(pem, passphrase, amended)
        if not um.verify_signature(amended, signature):
            raise SystemExit("that key is not one of the public keys built into the app: not uploading")
        (Path(work) / MANIFEST_NAME).write_bytes(amended)
        (Path(work) / SIGNATURE_NAME).write_bytes(signature)
        gh("release", "upload", tag, "--repo", REPO, "--clobber", str(Path(work) / MANIFEST_NAME), str(Path(work) / SIGNATURE_NAME))
    if not publish:
        print(f"signed {tag}. Check the draft, then publish it, then run: python packaging/sign_release.py --verify {tag}")
        return
    gh("release", "edit", tag, "--repo", REPO, "--draft=false", "--latest")
    print(f"signed and published {tag}; checking it the way the app will")
    for attempt in range(VERIFY_ATTEMPTS):
        try:
            verify_published(tag)
            return
        except (OSError, ValueError, SystemExit) as exc:
            if attempt == VERIFY_ATTEMPTS - 1:
                raise SystemExit(
                    f"{tag} is PUBLISHED but does not verify the way the app checks it ({exc}). Until that is fixed "
                    "the app offers it to nobody. Pull it (delete the release on GitHub) or fix the signature, then "
                    f"check again with: python packaging/sign_release.py --verify {tag}"
                )
            time.sleep(VERIFY_WAIT_SECONDS)


def verify_published(tag):
    """Fetch the public manifest and signature as the app does and check them against the embedded keys."""
    base = f"https://github.com/{REPO}/releases/download/{tag}"
    raw = urllib.request.urlopen(f"{base}/{MANIFEST_NAME}", timeout=30).read()
    signature = urllib.request.urlopen(f"{base}/{SIGNATURE_NAME}", timeout=30).read()
    if not um.verify_signature(raw, signature):
        raise SystemExit(f"{tag}: the published signature does NOT verify against the keys in the app")
    manifest = um.parse(raw)
    print(f"{tag}: signature ok, version {manifest.version}, min_version {manifest.min_version or '-'}, "
          f"{len(manifest.assets)} assets")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", nargs="?")
    parser.add_argument("--key", help="the private key file (signing by hand)")
    parser.add_argument("--ci", action="store_true", help="take the key and passphrase from UPDATE_SIGNING_KEY and UPDATE_SIGNING_PASSPHRASE")
    parser.add_argument("--publish", action="store_true", help="after signing, publish the draft and verify it")
    parser.add_argument("--min-version")
    parser.add_argument("--notice")
    parser.add_argument("--verify", metavar="TAG")
    args = parser.parse_args(argv)
    if args.verify:
        verify_published(args.verify)
    elif args.tag and args.ci:
        pem, passphrase = key_from_environment()
        sign_release(args.tag, None, args.min_version, args.notice, pem=pem, passphrase=passphrase, publish=args.publish)
    elif args.tag and args.key:
        sign_release(args.tag, args.key, args.min_version, args.notice, publish=args.publish)
    else:
        parser.error("give a tag and --key (or --ci), or --verify TAG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
