"""Run a packaged build for real and check that it works: CI's last gate before a zip.

    python packaging/smoke_test.py "path/to/Lit Review.exe"      (Windows)
    python packaging/smoke_test.py "Lit Review.app/Contents/MacOS/Lit Review"

It first runs `--self-check` (selfcheck.py), then starts the app on a spare port with throwaway data folders (never the real ones),
waits for /api/health, checks the page and a signed-in API call are served, then
starts a second copy, which must hand over and exit at once, and finally stops the
first. The tray is switched off (a CI machine may have no desktop); selfcheck.py
covers that its code is present.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

START_SECONDS = 90  # a first run unpacks and is scanned, so allow for it


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(url, token=None):
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def main(exe):
    port = free_port()
    work = tempfile.mkdtemp(prefix="lit-review-smoke-")
    env = dict(
        os.environ,
        LIT_REVIEW_PORT=str(port),
        LIT_REVIEW_DATA_DIR=os.path.join(work, "data"),
        LIT_REVIEW_CONFIG_DIR=os.path.join(work, "config"),
        LIT_REVIEW_NO_BROWSER="1",
        LIT_REVIEW_NO_DIALOG="1",
        LIT_REVIEW_NO_TRAY="1",
    )
    base = f"http://127.0.0.1:{port}"

    # First, does the build carry everything it loads at run time? The packaged app has
    # no console, so it reports through a file.
    report_path = os.path.join(work, "selfcheck.json")
    check = subprocess.run([exe, "--self-check"], env=dict(env, LIT_REVIEW_SELFCHECK_FILE=report_path), timeout=300)
    report = json.load(open(report_path, encoding="utf-8")) if os.path.exists(report_path) else {}
    print("self-check:", json.dumps(report.get("checks", "no report written"), indent=2))
    if check.returncode != 0 or not report.get("ok"):
        raise SystemExit("FAIL: the self-check found something missing")

    first = subprocess.Popen([exe], env=env)
    try:
        deadline = time.monotonic() + START_SECONDS
        health = None
        while time.monotonic() < deadline:
            if first.poll() is not None:
                raise SystemExit(f"FAIL: the app exited at once with code {first.returncode}")
            try:
                status, body = get(f"{base}/api/health")
                health = json.loads(body)
                break
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.5)
        if not health or health.get("app") != "lit-review":
            raise SystemExit(f"FAIL: no health answer within {START_SECONDS}s")
        print("health ok:", health)

        status, page = get(f"{base}/")
        if status != 200 or b'id="root"' not in page:
            raise SystemExit("FAIL: the page was not served")
        print("page ok:", len(page), "bytes")

        # The API refuses a stranger (no secret) and the packaged static files exist.
        try:
            get(f"{base}/api/update-check")
            raise SystemExit("FAIL: the API answered without the secret")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise SystemExit(f"FAIL: expected 401 without the secret, got {exc.code}")
        print("API refuses a stranger: ok")

        token = open(os.path.join(work, "data", "access.token"), encoding="utf-8").read().strip()
        status, body = get(f"{base}/api/about", token)
        about = json.loads(body)
        if status != 200 or not about.get("packaged"):
            raise SystemExit(f"FAIL: /api/about said {about}")
        print("signed-in API ok, version", about["version"])

        # A second launch must hand over to the first, not start another.
        second = subprocess.run([exe], env=env, timeout=90)
        if second.returncode != 0 or first.poll() is not None:
            raise SystemExit(f"FAIL: second launch exited {second.returncode}; first running: {first.poll() is None}")
        print("second launch handed over: ok")
    finally:
        first.terminate()
        try:
            first.wait(timeout=15)
        except subprocess.TimeoutExpired:
            first.kill()
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
