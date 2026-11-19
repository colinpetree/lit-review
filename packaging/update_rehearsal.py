"""Release check: the previous release really updates itself to this build, through the
in-app updater, as people's copies will. Run on every build leg for a real version (every
build on main, and a minor/major release's rebuild).

    python packaging/update_rehearsal.py --previous-zip Lit-Review-0.1.3-Windows.zip \
        --new-zip out/Lit-Review-0.1.4-Windows.zip --version 0.1.4

It unpacks the previous release into a throwaway folder (as a person's install), writes an
update manifest for the new zip signed with a throwaway key, and serves both from a server
on this computer. The previous release is started with the updater's test switches
(LIT_REVIEW_TESTING=1, LIT_REVIEW_UPDATE_BASE pointing at that server, LIT_REVIEW_UPDATE_PUBKEY
trusting the throwaway key; a normal run ignores both). Then, through its own API, as the
Settings page does: Check now, wait for the download to be staged, Install. The old copy's
update helper swaps the folders and starts the new one, which must answer as the new
version with the old install folder gone. Nothing reaches GitHub and no real key is used.
"""

import argparse
import base64
import functools
import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from app_runner import RunningApp, fresh_work, install_root, kill_programs_under, request, unpack_release_zip

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packaging"))

import update_manifest as um  # noqa: E402
from make_manifest import MANIFEST_NAME, SUFFIXES, sha256_of, unpacked_size  # noqa: E402

STAGE_SECONDS = 300  # download, unpack, and the new build's own --self-check
EXIT_SECONDS = 60  # the old copy quits once the helper has started
RESTART_SECONDS = 180


def signed_manifest(zip_path, version, key):
    """A one-platform manifest for `zip_path` and its signature, made the way
    make_manifest.py and sign_release.py make the real ones."""
    zip_path = Path(zip_path)
    platform = next(plat for suffix, plat in SUFFIXES.items() if zip_path.name.endswith(suffix))
    manifest = {
        "format": 1,
        "version": version,
        "tag": f"v{version}",
        "released": time.strftime("%Y-%m-%d"),
        "notice": "",
        "assets": [{
            "platform": platform,
            "name": zip_path.name,
            "size": zip_path.stat().st_size,
            "unpacked_size": unpacked_size(zip_path),
            "sha256": sha256_of(zip_path),
        }],
    }
    raw = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    signature = base64.b64encode(key.sign(um.SIGNATURE_PREFIX + raw))
    return raw, signature


def serve(directory):
    """A quiet static file server on loopback; returns (base URL, server)."""

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def explain(data_dir, install):
    """On a failure, print what the updater and the helper left behind, so the job log says why."""
    updates = Path(data_dir) / "updates"
    for name in ("result.json", "state.json", "started.json"):
        path = updates / name
        print(f"--- {path.name}: " + (path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "(none)"))
    log = Path(data_dir) / "logs" / "lit-review.log"
    if log.is_file():
        print("--- app log, last lines:")
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]))
    parent = install.parent
    print("--- install folder now holds:", sorted(p.name for p in parent.iterdir()) if parent.is_dir() else "(missing)")


def wait_for(check, seconds, what):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        ok, last = check()
        if ok:
            return last
        time.sleep(1)
    raise SystemExit(f"FAIL: {what} within {seconds}s (last: {last})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--previous-zip", required=True)
    parser.add_argument("--new-zip", required=True)
    parser.add_argument("--version", required=True, help="the new build's version, X.Y.Z")
    args = parser.parse_args(argv)
    if um.parse_version(args.version) is None:
        raise SystemExit(f"--version must be a plain X.Y.Z, not {args.version!r}")

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    work = Path(fresh_work("lit-review-rehearsal-"))
    old_exe = unpack_release_zip(args.previous_zip, work / "install")
    install = install_root(old_exe)

    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    site = work / "site"
    site.mkdir()
    raw, signature = signed_manifest(args.new_zip, args.version, key)
    (site / MANIFEST_NAME).write_bytes(raw)
    (site / (MANIFEST_NAME + ".sig")).write_bytes(signature)
    (site / Path(args.new_zip).name).write_bytes(Path(args.new_zip).read_bytes())
    base, server = serve(site)

    app = RunningApp(old_exe, work / "app", LIT_REVIEW_UPDATE_BASE=base, LIT_REVIEW_UPDATE_PUBKEY=public)
    try:
        app.start()
        _, about = app.call("/api/about")
        old_version = about.get("version")
        print(f"previous release {old_version} running from {install}")

        status, _ = app.call("/api/update/check", method="POST")
        if status not in (200, 202):
            raise SystemExit(f"FAIL: Check now answered {status}")

        def staged():
            _, update = app.call("/api/update-check")
            state = update.get("state") if isinstance(update, dict) else update
            if state in ("failed", "unsupported"):
                raise SystemExit(f"FAIL: the update went to '{state}': {update}")
            return state == "staged" and update.get("latest") == args.version, update

        wait_for(staged, STAGE_SECONDS, f"the previous release did not download and stage {args.version}")
        print(f"{args.version} downloaded, checked and staged")

        status, body = app.call("/api/update/apply", method="POST", timeout=60)
        if status not in (200, 202):
            raise SystemExit(f"FAIL: Install answered {status}: {body}")
        print("install started; waiting for the old copy to quit")

        # The old copy is this script's child. On macOS and Linux a child that has exited stays
        # in the process table (a zombie) until its parent collects it, and the update helper's
        # "is it still running?" check (os.kill(pid, 0)) counts a zombie as running: it would wait
        # 30 s, give up ("would not close") and start nothing. In real use the app's parent (the
        # Finder, launchd) collects it at once, so collect it here the same way.
        try:
            app.proc.wait(timeout=EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            raise SystemExit(f"FAIL: the previous release did not quit within {EXIT_SECONDS}s of Install")
        print("old copy quit; waiting for the new version to answer")

        def new_version_up():
            try:
                code, raw = request(f"{app.base}/api/about", token=app.token, timeout=3)
                version = json.loads(raw).get("version") if code == 200 else None
            except (OSError, ValueError):
                version = None
            return version == args.version, version

        wait_for(new_version_up, RESTART_SECONDS, f"version {args.version} did not start after the update")
        old_folder = install.with_name(install.name + ".old")
        wait_for(lambda: (not old_folder.exists(), old_folder.exists()), 60, "the old install folder was not removed")
        print(f"UPDATE REHEARSAL PASSED ({old_version} -> {args.version})")
    except SystemExit:
        explain(app.data_dir, install)
        raise
    finally:
        app.stop()
        kill_programs_under(work)  # the new copy was started by the helper, not by us
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
