"""Run a packaged build for real and check that it works: CI's first gate after a build.

    python packaging/smoke_test.py "path/to/Lit Review.exe"      (Windows)
    python packaging/smoke_test.py "Lit Review.app/Contents/MacOS/Lit Review"

It first runs `--self-check` (selfcheck.py), then starts the app on a spare port with throwaway data folders (never the real ones),
waits for /api/health, checks the page and a signed-in API call are served, then
starts a second copy, which must hand over and exit at once, and finally stops the
first. The tray is switched off (a CI machine may have no desktop); selfcheck.py
covers that its code is present. How a copy is started (throwaway folders, no browser,
the testing switch with LIT_REVIEW_NO_UPDATE_THREAD so it never reaches GitHub) is
app_runner.app_env, shared with the other release checks.
"""

import json
import os
import subprocess
import sys

from app_runner import RunningApp, fresh_work


def main(exe):
    work = fresh_work("lit-review-smoke-")
    app = RunningApp(exe, work)

    # First, does the build carry everything it loads at run time? The packaged app has
    # no console, so it reports through a file.
    report_path = os.path.join(work, "selfcheck.json")
    check = subprocess.run([exe, "--self-check"], env=dict(app.env, LIT_REVIEW_SELFCHECK_FILE=report_path), timeout=300)
    report = json.load(open(report_path, encoding="utf-8")) if os.path.exists(report_path) else {}
    print("self-check:", json.dumps(report.get("checks", "no report written"), indent=2))
    if check.returncode != 0 or not report.get("ok"):
        raise SystemExit("FAIL: the self-check found something missing")

    with app:
        print("health ok, port", app.port)

        status, page = app.call("/", token=False)
        if status != 200 or b'id="root"' not in page:
            raise SystemExit("FAIL: the page was not served")
        print("page ok:", len(page), "bytes")

        # The API refuses a stranger (no secret) and the packaged static files exist.
        status, _ = app.call("/api/update-check", token=False)
        if status != 401:
            raise SystemExit(f"FAIL: expected 401 without the secret, got {status}")
        print("API refuses a stranger: ok")

        status, about = app.call("/api/about")
        if status != 200 or not about.get("packaged"):
            raise SystemExit(f"FAIL: /api/about said {about}")
        print("signed-in API ok, version", about["version"])

        # The license notices travel inside the app; the Settings page reads them here.
        status, body = app.call("/api/notices")
        notices = body.get("text", "") if isinstance(body, dict) else ""
        if status != 200 or len(notices) < 10_000 or "Lit Review includes" not in notices:
            raise SystemExit(f"FAIL: /api/notices gave status {status} and {len(notices)} characters")
        print("third-party notices ok:", len(notices), "characters")

        # The update status is served, nothing is being checked, and the setting starts off.
        status, update = app.call("/api/update-check")
        if status != 200 or update.get("state") != "idle" or update.get("auto_apply") is not False:
            raise SystemExit(f"FAIL: /api/update-check said {update}")
        print("update status ok:", update["state"])

        # A second launch must hand over to the first, not start another.
        second = subprocess.run([exe], env=app.env, timeout=90)
        if second.returncode != 0 or app.proc.poll() is not None:
            raise SystemExit(f"FAIL: second launch exited {second.returncode}; first running: {app.proc.poll() is None}")
        print("second launch handed over: ok")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
