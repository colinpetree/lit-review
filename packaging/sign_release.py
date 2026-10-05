"""Sign a draft release's update manifest (run by the maintainer, after trying the downloads).

    python packaging/sign_release.py v0.1.0 --key D:\\keys\\lit-review-active.pem
    python packaging/sign_release.py v0.1.0 --key ... --min-version 0.1.0 --notice "Model X was retired."
    python packaging/sign_release.py --verify v0.1.0

Needs the GitHub CLI (`gh`), signed in. It downloads the draft's zips and manifest, re-hashes
every zip against the manifest (so a zip swapped after the build cannot be signed by
accident), asks for the key's passphrase, signs, checks the signature against the public keys
built into the app, and uploads `update-manifest.json.sig`. Then you publish the release.

`--min-version` and `--notice` change the manifest (it is rewritten, then signed): a version
older than `--min-version` is treated as one that must update. Use it only for a version that
really can no longer work, and only after trying the update path on a real machine.

`--verify TAG` downloads a PUBLISHED release's manifest and signature the way the app does and
checks them against the embedded keys. Run it after every publish.
"""

import argparse
import base64
import getpass
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import update_manifest as um  # noqa: E402
from make_manifest import MANIFEST_NAME, sha256_of  # noqa: E402
from updates import REPO  # noqa: E402

SIGNATURE_NAME = MANIFEST_NAME + ".sig"


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


def gh(*args):
    return subprocess.run(["gh", *args], check=True)


def sign_release(tag, key_path, min_version=None, notice=None):
    if not um.PUBLIC_KEYS:
        raise SystemExit("backend/update_manifest.py has no PUBLIC_KEYS yet: run make_update_key.py and paste them in first")
    with tempfile.TemporaryDirectory() as work:
        gh("release", "download", tag, "--repo", REPO, "--dir", work, "--pattern", "*.zip", "--pattern", MANIFEST_NAME)
        raw = (Path(work) / MANIFEST_NAME).read_bytes()
        manifest = check_assets(raw, work)
        if manifest.tag != tag:
            raise SystemExit(f"the manifest is for {manifest.tag}, not {tag}")
        amended = amend(raw, min_version, notice)
        if amended != raw:
            check_assets(amended, work)
        passphrase = getpass.getpass("Key passphrase: ").encode()
        signature = sign(Path(key_path).read_bytes(), passphrase, amended)
        if not um.verify_signature(amended, signature):
            raise SystemExit("that key is not one of the public keys built into the app: not uploading")
        (Path(work) / MANIFEST_NAME).write_bytes(amended)
        (Path(work) / SIGNATURE_NAME).write_bytes(signature)
        gh("release", "upload", tag, "--repo", REPO, "--clobber", str(Path(work) / MANIFEST_NAME), str(Path(work) / SIGNATURE_NAME))
    print(f"signed {tag}. Check the draft, then publish it, then run: python packaging/sign_release.py --verify {tag}")


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
    parser.add_argument("--key")
    parser.add_argument("--min-version")
    parser.add_argument("--notice")
    parser.add_argument("--verify", metavar="TAG")
    args = parser.parse_args(argv)
    if args.verify:
        verify_published(args.verify)
    elif args.tag and args.key:
        sign_release(args.tag, args.key, args.min_version, args.notice)
    else:
        parser.error("give a tag and --key, or --verify TAG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
