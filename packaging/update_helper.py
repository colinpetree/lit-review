"""Swaps a staged Lit Review in place of the installed one, starts it, and rolls back if it
does not come up.

The running app cannot replace the folder it runs from, so it starts this program, which is
copied out of the install folder first, and exits. Standard library only: it is built into a
small standalone executable, and it must work when everything else is mid-change.

    update_helper --install DIR --new DIR --old DIR --exe RELPATH --pid N
                  --marker FILE --version X.Y.Z --result FILE [--wait-seconds 90]

Order, chosen so a failure at any step leaves a working install:
  1. wait for the old process to exit (terminate it after a while)
  2. rename install -> old            (retried: antivirus and Explorer can hold a folder briefly)
  3. rename new -> install            (right after; if it cannot, put old back)
  4. start the new app, wait for it to write `marker` with the expected version
  5. marker seen: delete old.  Not seen in time: stop it, put old back, start the old app.
`result` says what happened, for the next launch to tell the user. Every path is absolute and
becomes an argument, never part of a command line string, so odd characters in a profile name
(%, &, ^, spaces) cannot change what runs.

The one case this cannot undo is the helper being killed between the two renames: `old` and
`new` then both exist and `install` does not. INSTALL.md says how to recover by hand.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SWAPPED, UNCHANGED, RESTORED, STRANDED = "swapped", "unchanged", "restored", "stranded"

EXIT_WAIT_SECONDS = 30
RENAME_RETRY_SECONDS = 60
MARKER_POLL_SECONDS = 0.5


class ArgumentError(Exception):
    pass


# ---------------------------------------------------------------- arguments

def _absolute(value, what):
    if not value or any(ch in value for ch in "\r\n\0") or not os.path.isabs(value):
        raise ArgumentError(f"{what} must be an absolute path without line breaks")
    return Path(os.path.normpath(value))


def validate(args):
    """The cleaned paths, or ArgumentError. install, new and old must be siblings, so each
    rename stays on one disk, and the app's own executable must sit inside `install`."""
    install = _absolute(args.install, "--install")
    new = _absolute(args.new, "--new")
    old = _absolute(args.old, "--old")
    marker = _absolute(args.marker, "--marker")
    result = _absolute(args.result, "--result")
    if len({install, new, old}) != 3 or not (install.parent == new.parent == old.parent):
        raise ArgumentError("install, new and old must be different folders in the same parent")
    if not new.is_dir() or not install.is_dir():
        raise ArgumentError("install and new must both exist")
    if old.exists():
        raise ArgumentError("old already exists")
    exe = Path(args.exe)
    if exe.is_absolute() or ".." in exe.parts or not exe.parts:
        raise ArgumentError("--exe must be a path inside the install folder")
    if not (new / exe).is_file():
        raise ArgumentError("the new build has no such executable")
    return install, new, old, exe, marker, result


# ---------------------------------------------------------------- swapping

def _retry(action, timeout, sleep, clock):
    """None once `action` succeeds, else the last OSError after `timeout` seconds."""
    deadline = clock() + timeout
    while True:
        try:
            action()
            return None
        except OSError as exc:
            if clock() >= deadline:
                return exc
            sleep(0.5)


def swap(install, new, old, *, rename=os.rename, sleep=time.sleep, clock=time.monotonic, timeout=RENAME_RETRY_SECONDS):
    """Put `new` where `install` is and keep the previous one as `old`.

    SWAPPED    install now holds the new build, old holds the previous one.
    UNCHANGED  the first rename never worked: nothing was touched.
    RESTORED   the second rename failed and the previous build was put back.
    STRANDED   both failed: install is missing (old and new exist); needs a person.

    Returns `(outcome, detail)`: detail is the last operating system error, "" for SWAPPED.
    """
    error = _retry(lambda: rename(install, old), timeout, sleep, clock)
    if error:
        return UNCHANGED, str(error)
    error = _retry(lambda: rename(new, install), timeout, sleep, clock)
    if error is None:
        return SWAPPED, ""
    if _retry(lambda: rename(old, install), timeout, sleep, clock) is None:
        return RESTORED, str(error)
    return STRANDED, str(error)


def roll_back(install, old, failed, *, rename=os.rename, sleep=time.sleep, clock=time.monotonic, timeout=RENAME_RETRY_SECONDS):
    """Undo a swap whose new build did not come up: the new tree is set aside as `failed`
    and the previous one restored. True when the previous build is back in place."""
    if _retry(lambda: rename(install, failed), timeout, sleep, clock):
        return False
    return _retry(lambda: rename(old, install), timeout, sleep, clock) is None


# ---------------------------------------------------------------- processes

def pid_running(pid):
    """Whether process `pid` is alive. (os.kill(pid, 0) is not a probe on Windows: it
    would terminate the process.)"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_pid(pid):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
        else:
            os.kill(pid, 15)
    except OSError:
        pass


def wait_for_exit(pid, timeout, *, running=pid_running, terminate=terminate_pid, sleep=time.sleep, clock=time.monotonic):
    """Wait for `pid` to end; after `timeout` seconds stop it (SQLite writes are atomic, so
    this loses nothing the app had committed). True when it is gone."""
    deadline = clock() + timeout
    while running(pid):
        if clock() >= deadline:
            terminate(pid)
            deadline = clock() + 10
            while running(pid):
                if clock() >= deadline:
                    return False
                sleep(0.2)
            return True
        sleep(0.2)
    return True


def start_app(exe, extra_args=()):
    """Start the app detached from this helper, with an argument list (no shell)."""
    # This helper is itself a PyInstaller program: without the reset, the app it starts would inherit
    # the helper's bootloader variables (its files, its archive) instead of starting on its own.
    kwargs = {"cwd": str(Path(exe).parent), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "env": {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen([str(exe), *extra_args], **kwargs)


# ---------------------------------------------------------------- the marker and the result

def marker_ok(marker, version):
    try:
        data = json.loads(Path(marker).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("version") == version


def wait_for_marker(marker, version, timeout, *, sleep=time.sleep, clock=time.monotonic, alive=lambda: True):
    """True once the new app has written `marker` naming `version`. False on timeout, or as
    soon as `alive()` says the new process has already exited (no point waiting)."""
    deadline = clock() + timeout
    while clock() < deadline:
        if marker_ok(marker, version):
            return True
        if not alive():
            return marker_ok(marker, version)
        sleep(MARKER_POLL_SECONDS)
    return marker_ok(marker, version)


def write_result(path, status, reason="", version=""):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"status": status, "reason": reason, "version": version}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # nothing more can be done; the app notices the missing result


def remove_tree(path, attempts=5, *, sleep=time.sleep):
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not Path(path).exists():
            return True
        sleep(1)
    return False


# ---------------------------------------------------------------- the whole job

def run(args, *, start=start_app, wait_exit=wait_for_exit, do_swap=swap, do_roll_back=roll_back,
        marker_wait=wait_for_marker, cleanup=remove_tree):
    """0 installed, 1 not installed (previous version kept), 2 a person must recover it."""
    try:
        install, new, old, exe, marker, result = validate(args)
    except ArgumentError as exc:
        write_result(args.result, "not_installed", f"The update helper was given bad arguments: {exc}", args.version)
        return 1

    def previous(reason, status="not_installed"):
        write_result(result, status, reason, args.version)
        try:
            start(install / exe)
        except OSError:
            pass  # nothing more to try: the user opens the app themselves, and the result says why
        return 1

    if not wait_exit(args.pid, EXIT_WAIT_SECONDS):
        # Nothing was touched and the old copy is still running, so there is nothing to start.
        write_result(result, "not_installed", "The old copy of Lit Review would not close.", args.version)
        return 1
    try:
        marker.unlink()  # a marker left by an earlier attempt must not count
    except FileNotFoundError:
        pass
    except OSError:
        pass

    outcome, detail = do_swap(install, new, old)
    # The detail is the operating system's own words for what went wrong. The app logs the reason, so a
    # failure that cannot be reproduced can still be told apart afterwards.
    why = f" (details: {detail})" if detail else ""
    if outcome == STRANDED:
        write_result(result, "stranded", f"The folders could not be switched; see INSTALL.md to recover{why}.", args.version)
        return 2
    if outcome in (UNCHANGED, RESTORED):
        step = "put the new version in place" if outcome == RESTORED else "replace the old folder"
        return previous(f"Windows or macOS would not let the helper {step} (an open window or a security tool may be using it){why}.")

    try:
        child = start(install / exe, ["--after-update"])
    except OSError as exc:
        child = None  # the new program could not even be started: treated like one that never came up
        how_it_failed = f"it could not be started ({exc})"
    else:
        how_it_failed = ""
    alive = (lambda: child.poll() is None) if hasattr(child, "poll") else (lambda: child is not None)
    if child is not None and marker_wait(marker, args.version, args.wait_seconds, alive=alive):
        cleanup(old)
        write_result(result, "installed", "", args.version)
        return 0

    if child is not None:
        code = child.poll() if hasattr(child, "poll") else None
        how_it_failed = (f"it closed with exit code {code} before it was ready" if code is not None
                         else f"it was not ready after {args.wait_seconds:g} seconds")
    try:
        child.terminate()
    except (OSError, AttributeError):
        pass
    failed = install.with_name(install.name + ".failed")
    if do_roll_back(install, old, failed):
        write_result(result, "rolled_back", f"The new version did not start ({how_it_failed}), so the previous version was "
                     "restored. A system security prompt may have blocked it.", args.version)
        try:
            start(install / exe)
        except OSError:
            pass
        cleanup(failed)
        return 1
    write_result(result, "stranded", f"The new version did not start ({how_it_failed}) and the previous one could not be restored; see INSTALL.md.", args.version)
    return 2


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--old", required=True)
    parser.add_argument("--exe", required=True, help="the app's executable, relative to the install folder")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--wait-seconds", type=float, default=90)
    return parser.parse_args(argv)


def main(argv=None):
    return run(parse_args(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
