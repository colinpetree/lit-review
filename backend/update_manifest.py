"""The signed list of what a release holds, and the check that it is really ours.

Releases are not code-signed, so the app cannot trust a download because of who made
the file. Instead each release carries `update-manifest.json` (the version, a notice
and, for each platform's zip, its size and SHA-256) and `update-manifest.json.sig`, an
Ed25519 signature made with a private key the maintainer keeps offline. The app holds
only the public keys. Someone who takes over the GitHub account or the build cannot
ship an update, because they cannot sign.

Rules, all of which fail closed (a bad manifest means "no update", never a guess):
- The signature covers the raw manifest bytes exactly as downloaded, with a domain
  prefix, and is checked before the bytes are parsed or re-serialised.
- The manifest's version must match its tag and be strictly newer than the running
  version (no downgrade, no replay of an old signed release).
- A zip's name is a plain file name, and its hash and size are well formed.

`min_version` (optional, signed) names the oldest version still allowed to run, for the
day an old build can no longer work (a retired AI model): a running version below it is
"required", which the updater treats as auto-apply.
"""

import base64
import binascii
import json
import os
import platform
import re
import sys
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from updates import parse_version

FORMAT = 1
SIGNATURE_PREFIX = b"lit-review-update-v1\n"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_NOTICE_CHARS = 1000

# Base64 of each trusted raw Ed25519 public key: the active one and a spare, so a lost or
# leaked key can be rotated by an ordinary release. Filled in by packaging/make_update_key.py;
# while it is empty no manifest verifies and the app only shows the old "a new version exists"
# notice.
PUBLIC_KEYS = [
    "zNOux9BUehAh0gixqsOypcRtKlK/XRJKf9Li3ML36Qw=",
    "OMoSgJBSd0Ns/vgkqeqqW0anD6NfDdGxnJaljICFf0s=",
]

PLATFORMS = ("windows", "macos-apple-silicon", "macos-intel")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.zip$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ZIP_BYTES = 2 * 1024**3


class ManifestError(Exception):
    """The manifest cannot be trusted or used; the message is for the log."""


@dataclass(frozen=True)
class Asset:
    platform: str
    name: str
    size: int
    unpacked_size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    version: str
    tag: str
    released: str
    notice: str
    min_version: str | None
    assets: tuple


def testing_enabled():
    return os.environ.get("LIT_REVIEW_TESTING") == "1"


def trusted_keys():
    """The public keys a manifest may be signed with. `LIT_REVIEW_UPDATE_PUBKEY` (a test key)
    is honoured only when `LIT_REVIEW_TESTING=1`; a production run ignores it, so no
    environment variable can make the app trust another key."""
    keys = list(PUBLIC_KEYS)
    extra = os.environ.get("LIT_REVIEW_UPDATE_PUBKEY") if testing_enabled() else None
    if extra:
        keys.append(extra)
    return keys


def _load_key(text):
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(text, validate=True))
    except (binascii.Error, ValueError, TypeError):
        return None


def verify_signature(raw, signature, keys=None):
    """True if `signature` (base64 text or raw bytes) is a valid signature by one of the
    trusted keys over the domain-prefixed `raw` manifest bytes."""
    if isinstance(signature, str):
        signature = signature.encode()
    try:
        signature = base64.b64decode(signature.strip(), validate=True)
    except (binascii.Error, ValueError):
        return False
    for text in trusted_keys() if keys is None else keys:
        key = _load_key(text)
        if key is None:
            continue
        try:
            key.verify(signature, SIGNATURE_PREFIX + raw)
            return True
        except InvalidSignature:
            continue
    return False


def _text(data, field, limit=200):
    value = data.get(field)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ManifestError(f"the manifest has no usable {field}")
    return value


def _count(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= _MAX_ZIP_BYTES:
        raise ManifestError(f"the manifest's {field} is not a sensible size")
    return value


def _asset(data):
    if not isinstance(data, dict):
        raise ManifestError("an asset entry is not an object")
    plat, name, digest = data.get("platform"), data.get("name"), data.get("sha256")
    if plat not in PLATFORMS:
        raise ManifestError(f"unknown platform {plat!r}")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ManifestError(f"unsafe file name {name!r}")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ManifestError("an asset has no valid sha256")
    return Asset(plat, name, _count(data.get("size"), "size"), _count(data.get("unpacked_size"), "unpacked_size"), digest)


def parse(raw):
    """A Manifest from raw bytes that are ALREADY verified. Raises ManifestError."""
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("the manifest is too large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError("the manifest is not JSON") from exc
    if not isinstance(data, dict):
        raise ManifestError("the manifest is not an object")
    if data.get("format") != FORMAT or isinstance(data.get("format"), bool):
        raise ManifestError(f"unsupported manifest format {data.get('format')!r}")

    version, tag = _text(data, "version"), _text(data, "tag")
    parsed = parse_version(version)
    if parsed is None or ".".join(map(str, parsed)) != version:
        raise ManifestError(f"{version!r} is not a plain version number")
    if tag != f"v{version}":
        raise ManifestError(f"the tag {tag!r} does not match version {version!r}")

    minimum = data.get("min_version")
    if minimum is not None and (not isinstance(minimum, str) or parse_version(minimum) is None):
        raise ManifestError("min_version is not a version number")

    notice = data.get("notice", "")
    if not isinstance(notice, str):
        raise ManifestError("notice is not text")

    raw_assets = data.get("assets")
    if not isinstance(raw_assets, list) or not 0 < len(raw_assets) <= len(PLATFORMS):
        raise ManifestError("the manifest lists no usable assets")
    assets = tuple(_asset(item) for item in raw_assets)
    if len({a.platform for a in assets}) != len(assets):
        raise ManifestError("a platform is listed twice")

    released = data.get("released", "")
    return Manifest(
        version=version,
        tag=tag,
        released=released if isinstance(released, str) else "",
        notice=notice[:MAX_NOTICE_CHARS],
        min_version=minimum,
        assets=assets,
    )


def load(raw, signature, running_version):
    """The verified Manifest for a release newer than `running_version`, else ManifestError.
    A development build (no version number) is never offered anything."""
    if not verify_signature(raw, signature):
        raise ManifestError("the signature does not match a trusted key")
    manifest = parse(raw)
    mine, theirs = parse_version(running_version), parse_version(manifest.version)
    if mine is None:
        raise ManifestError("this is a development build")
    if theirs <= mine:
        raise ManifestError(f"{manifest.version} is not newer than {running_version}")
    return manifest


def is_required(manifest, running_version):
    """True when the running version is older than the manifest's `min_version`."""
    mine = parse_version(running_version)
    floor = parse_version(manifest.min_version) if manifest.min_version else None
    return bool(mine and floor and mine < floor)


def platform_key(machine=None, plat=None):
    """Which asset this computer takes, or None where there is no packaged build."""
    plat = plat or sys.platform
    machine = (machine or platform.machine()).lower()
    if plat == "win32":
        return "windows"
    if plat == "darwin":
        return "macos-apple-silicon" if machine in ("arm64", "aarch64") else "macos-intel"
    return None


def asset_for(manifest, plat=None):
    plat = plat or platform_key()
    return next((a for a in manifest.assets if a.platform == plat), None)
