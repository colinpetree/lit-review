"""Start a real copy of Lit Review for a check, talk to it, and stop it. Shared by the
release checks that run a packaged build: smoke_test.py, upgrade_test.py,
update_rehearsal.py and browser_test.py. Standard library only.

A copy always gets throwaway data and config folders (never the runner's or your real
ones), a spare port, no browser, dialog or tray, and the testing switch with the update
thread off, so it never reaches GitHub or the usage counter.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

START_SECONDS = 90  # a first run unpacks and is scanned, so allow for it
APP_FOLDER = "Lit Review"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if port == 8100:  # a real copy may be running there
        return free_port()
    return port


def app_env(work, port, **extra):
    """The environment a checked copy runs with: its own folders under `work`, no browser, dialog
    or tray, and the testing switch with the update thread off (so a packaged app never checks
    GitHub on its own; the testing switch also keeps the usage counter on loopback only)."""
    env = dict(
        os.environ,
        LIT_REVIEW_PORT=str(port),
        LIT_REVIEW_DATA_DIR=os.path.join(work, "data"),
        LIT_REVIEW_CONFIG_DIR=os.path.join(work, "config"),
        LIT_REVIEW_NO_BROWSER="1",
        LIT_REVIEW_NO_DIALOG="1",
        LIT_REVIEW_NO_TRAY="1",
        LIT_REVIEW_TESTING="1",
        LIT_REVIEW_NO_UPDATE_THREAD="1",
    )
    env.update({k: str(v) for k, v in extra.items()})
    return env


def request(url, *, token=None, method="GET", body=None, timeout=10):
    """(status, raw bytes). An HTTP error status is returned, not raised."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def kill_tree(proc):
    """Stop a process and everything it started (on Windows a frozen app runs as a bootloader
    plus a child, and an update helper may have started more)."""
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        pass


def kill_programs_under(folder):
    """Stop any program whose executable lives under `folder`: the copy an update helper started
    is not our child, so it cannot be stopped by process id. Best effort."""
    folder = str(Path(folder).resolve())
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
            f"$_.ExecutablePath.StartsWith('{folder}', [StringComparison]::OrdinalIgnoreCase) }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", folder], capture_output=True)


def exe_in(folder):
    """The program inside an unpacked build folder (what a release zip holds)."""
    folder = Path(folder)
    if sys.platform == "darwin":
        return folder / f"{APP_FOLDER}.app" / "Contents" / "MacOS" / APP_FOLDER
    return folder / APP_FOLDER / f"{APP_FOLDER}.exe"


def install_root(exe):
    """The folder the updater swaps: `Lit Review` on Windows, `Lit Review.app` on a Mac."""
    exe = Path(exe)
    return exe.parents[2] if sys.platform == "darwin" else exe.parent


def unpack_release_zip(zip_path, dest):
    """Unpack a release zip the way the updater does and return the program inside. On a Mac
    `ditto` keeps the app's signature and bundle attributes (`unzip` would not)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(dest)], check=True)
    else:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(dest)
    exe = exe_in(dest)
    if not exe.is_file():
        raise SystemExit(f"FAIL: {zip_path} did not hold {exe.relative_to(dest)}")
    return exe


class RunningApp:
    """One copy of the app, started with `app_env`. Use as a context manager: it is always stopped."""

    def __init__(self, exe, work, *, port=None, args=(), **extra_env):
        self.exe = str(exe)
        self.work = str(work)
        self.port = port or free_port()
        self.args = list(args)
        self.env = app_env(self.work, self.port, **extra_env)
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = None
        self.token = None

    @property
    def data_dir(self):
        return Path(self.work) / "data"

    @property
    def output_path(self):
        return Path(self.work) / "app-output.log"

    def start(self, wait=True):
        # What a source run prints (request lines, the private link) goes to a file in the
        # throwaway folder, not the job log; a packaged app prints nothing.
        Path(self.work).mkdir(parents=True, exist_ok=True)
        self._output = open(self.output_path, "ab")
        self.proc = subprocess.Popen([self.exe, *self.args], env=self.env, stdout=self._output, stderr=subprocess.STDOUT)
        if wait:
            self.wait_until_up()
        return self

    def wait_until_up(self, seconds=START_SECONDS, *, process_may_exit=False):
        """Wait for /api/health, then read the copy's secret from its data folder."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not process_may_exit and self.proc is not None and self.proc.poll() is not None:
                raise SystemExit(f"FAIL: the app exited at once with code {self.proc.returncode}")
            try:
                status, body = request(f"{self.base}/api/health", timeout=3)
                if status == 200 and json.loads(body).get("app") == "lit-review":
                    self.token = (self.data_dir / "access.token").read_text(encoding="utf-8").strip()
                    return json.loads(body)
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.5)
        raise SystemExit(f"FAIL: no health answer within {seconds}s")

    def call(self, path, *, method="GET", body=None, token=True, timeout=10):
        """(status, parsed JSON or raw bytes) for an API path, signed in unless token=False."""
        status, raw = request(f"{self.base}{path}", token=self.token if token else None, method=method, body=body, timeout=timeout)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw

    def stop(self):
        if self.proc is not None:
            kill_tree(self.proc)
        if getattr(self, "_output", None):
            self._output.close()
            self._output = None

    def output_tail(self, lines=40):
        try:
            return "\n".join(self.output_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""


    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def fresh_work(prefix):
    import tempfile

    return tempfile.mkdtemp(prefix=prefix)


def remove(path):
    shutil.rmtree(path, ignore_errors=True)
