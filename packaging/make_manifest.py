"""Write `update-manifest.json` for a release: the list of the platform zips with their sizes
and SHA-256, which the maintainer then signs (sign_release.py). The app trusts only a manifest
carrying a valid signature, so this unsigned file in a draft release can be used by nobody.

    python packaging/make_manifest.py --version 0.1.0 --dir out

Run by the release workflow after the zips are all in one folder. It lists the `.zip` files
only and requires exactly three, one per platform, so a disk image (`.dmg`, for people) can
never be mistaken for something the updater installs.
"""

import argparse
import datetime
import hashlib
import json
import sys
import zipfile
from pathlib import Path

# The end of each zip's name decides its platform (the workflow names them
# Lit-Review-<version>-<Windows|macOS-Apple-Silicon|macOS-Intel>.zip).
SUFFIXES = {
    "-Windows.zip": "windows",
    "-macOS-Apple-Silicon.zip": "macos-apple-silicon",
    "-macOS-Intel.zip": "macos-intel",
}
MANIFEST_NAME = "update-manifest.json"


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unpacked_size(path):
    with zipfile.ZipFile(path) as archive:
        return sum(info.file_size for info in archive.infolist())


def build(directory, version, notice="", min_version=None, today=None):
    """The manifest as bytes, from the zips in `directory`. Exits with a message if the set of zips is wrong."""
    directory = Path(directory)
    zips = sorted(directory.glob("*.zip"))
    if len(zips) != len(SUFFIXES):
        raise SystemExit(f"expected {len(SUFFIXES)} zips in {directory}, found {len(zips)}: {[z.name for z in zips]}")
    assets = {}
    for path in zips:
        matches = [plat for suffix, plat in SUFFIXES.items() if path.name.endswith(suffix)]
        if len(matches) != 1 or not path.name.startswith(f"Lit-Review-{version}-"):
            raise SystemExit(f"{path.name} is not a Lit-Review-{version}-<platform>.zip")
        assets[matches[0]] = {
            "platform": matches[0],
            "name": path.name,
            "size": path.stat().st_size,
            "unpacked_size": unpacked_size(path),
            "sha256": sha256_of(path),
        }
    if set(assets) != set(SUFFIXES.values()):
        raise SystemExit(f"the zips do not cover every platform: {sorted(assets)}")
    manifest = {
        "format": 1,
        "version": version,
        "tag": f"v{version}",
        "released": (today or datetime.date.today()).isoformat(),
        "notice": notice,
        "assets": [assets[plat] for plat in SUFFIXES.values()],
    }
    if min_version:
        manifest["min_version"] = min_version
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--notice", default="")
    parser.add_argument("--min-version", default=None)
    args = parser.parse_args(argv)
    raw = build(args.dir, args.version, args.notice, args.min_version)
    (Path(args.dir) / MANIFEST_NAME).write_bytes(raw)
    print(raw.decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
