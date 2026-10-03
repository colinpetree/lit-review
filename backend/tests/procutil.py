"""Helpers for tests that start real copies of the app as separate processes."""

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import app as app_module

BACKEND_DIR = Path(__file__).resolve().parent.parent
REAL_PORT = 5175  # a real app may be running here; tests must never touch it
RUNNING_AT = re.compile(r"Lit Review is running at http://127\.0\.0\.1:(\d+)")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != REAL_PORT
    return port


def free_port_run(count):
    """The first port of `count` consecutive ports that nothing is using, so a
    test can tell a copy to start at the first and watch where it ends up."""
    for _ in range(200):
        start = free_port()
        if start + count >= 65535:
            continue
        holders = []
        try:
            for port in range(start, start + count):
                sock = socket.socket()
                sock.bind(("127.0.0.1", port))
                holders.append(sock)
        except OSError:
            continue
        finally:
            for sock in holders:
                sock.close()
        if REAL_PORT not in range(start, start + count):
            return start
    raise RuntimeError("no run of free ports found")


def kill_tree(proc):
    """Stop a process and everything it started. On Windows the venv's python.exe
    is a launcher that starts the real interpreter as a child, so stopping only
    the launcher would leave the app (and its port and lock) running."""
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.kill()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        pass


class Copy:
    """One real `python app.py` process, with its own data folders, asked to start
    on `port` (it may end up on a later one). It prints "Would open <url>"
    instead of opening a browser."""

    def __init__(self, port, data_dir, config_dir, script="app.py", extra_env=None):
        assert port != REAL_PORT, "tests must never use the real app's port"
        self.data_dir = Path(data_dir)
        self.config_dir = Path(config_dir)
        env = {
            **os.environ,
            "LIT_REVIEW_PORT": str(port),
            "LIT_REVIEW_DATA_DIR": str(data_dir),
            "LIT_REVIEW_CONFIG_DIR": str(config_dir),
            "LIT_REVIEW_NO_BROWSER": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            **(extra_env or {}),
        }
        self.requested_port = port
        self.proc = subprocess.Popen(
            [sys.executable, script],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        self._lines = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        for line in self.proc.stdout:
            self._lines.append(line)

    @property
    def output(self):
        return "".join(self._lines)

    @property
    def port(self):
        """The port it is actually running on (it says so), or None if it has not said."""
        match = RUNNING_AT.search(self.output)
        return int(match.group(1)) if match else None

    @property
    def token(self):
        """The secret it uses, read from its own file, as only its own user could."""
        return (self.data_dir / "access.token").read_text(encoding="utf-8").strip()

    def alive(self):
        return self.proc.poll() is None

    def wait_exit(self, timeout):
        """The exit code, or None if it is still running after `timeout` seconds."""
        try:
            code = self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return None
        self._reader.join(5)
        return code

    def wait_serving(self, timeout=30):
        """Whether it answers as the app (on the port it chose) within `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.alive():
                return False
            port = self.port
            if port and app_module.check_port(port) == "ours":
                return True
            time.sleep(0.2)
        return False

    def kill(self):
        kill_tree(self.proc)
        self._reader.join(5)
