"""Release checks that drive the app's pages in a real browser (Chromium, through Playwright).

    python packaging/browser_test.py "dist/Lit Review/Lit Review.exe" [--artifacts DIR]
    python packaging/browser_test.py --source [--artifacts DIR]
    python packaging/browser_test.py --jobs [--artifacts DIR]

The first two walk the pages (frontend/scripts/verify-app.mjs) on sample data made by
backend/ci_fixture.py, in a packaged build or a source run (python backend/app.py).

--jobs is the background-job flow (frontend/scripts/verify-jobs.mjs): a source run started by
backend/tests/e2e_server.py, with the AI and the paper sources faked and the network refused,
on an empty data folder: a dataset is searched, an evaluation graded, stopped and resumed.

Each copy gets throwaway folders (app_runner: no browser, tray or dialog, never reaching
GitHub) and is always stopped. Needs `npm ci` in frontend/ and Playwright's Chromium
(`npx playwright install chromium`).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from app_runner import RunningApp, fresh_work

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", nargs="?")
    parser.add_argument("--source", action="store_true", help="walk the pages on a source run (python backend/app.py)")
    parser.add_argument("--jobs", action="store_true", help="the job flow, on a source run with fakes")
    parser.add_argument("--artifacts")
    args = parser.parse_args(argv)
    if sum([bool(args.exe), args.source, args.jobs]) != 1:
        parser.error("give a packaged program, --source or --jobs")

    work = fresh_work("lit-review-browser-")
    if args.jobs:
        app = RunningApp(sys.executable, work, args=[str(ROOT / "backend" / "tests" / "e2e_server.py")])
        command = ["node", "scripts/verify-jobs.mjs"]
    else:
        manifest = os.path.join(work, "fixture.json")
        env = dict(os.environ, LIT_REVIEW_CONFIG_DIR=os.path.join(work, "config"))
        subprocess.run(
            [sys.executable, str(ROOT / "backend" / "ci_fixture.py"), "--data-dir", os.path.join(work, "data"), "--manifest", manifest],
            check=True, env=env, stdout=subprocess.DEVNULL,
        )
        program = args.exe or sys.executable
        app = RunningApp(program, work, args=[] if args.exe else [str(ROOT / "backend" / "app.py")])
        command = ["node", "scripts/verify-app.mjs", "--manifest", manifest]
    if args.artifacts:
        command += ["--artifacts", str(Path(args.artifacts).resolve())]
    with app:
        # The secret is only ever this throwaway copy's.
        result = subprocess.run([*command, "--base", app.base, "--token", app.token], cwd=ROOT / "frontend")
    if result.returncode != 0:
        print("--- the app's own output, last lines:")
        print(app.output_tail())
        raise SystemExit("FAIL: the browser check found problems (above)")
    print("BROWSER TEST PASSED")


if __name__ == "__main__":
    main()
