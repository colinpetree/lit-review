"""Finds, downloads and stages a new Lit Review in the background, then hands the swap to
the update helper. See update_manifest.py for how a release is trusted, and
packaging/update_helper.py for the swap itself.

Lifecycle of one release:
  idle -> available -> downloading -> staged -> (applying) -> the new copy runs
                   \\-> failed | unsupported

- Always on in a packaged app (a background thread: 30 s after start, then every 24 h). A
  copy run from source never installs anything.
- The download resumes where it stopped (a short-session user would otherwise never finish
  one), is limited to GitHub's hosts across redirects, and must match the signed size and
  SHA-256 before it is used.
- It is unpacked next to the install folder, checked (zip entry names, the macOS signature,
  and the new build's own `--self-check` reporting the expected version) and left staged.
- With `auto_apply` on, or when the running version is below the manifest's `min_version`,
  the staged copy is installed at the next launch (`apply_at_launch`); otherwise the page
  offers "Install and restart" (`start_apply`). It is never swapped mid-run on its own.
- `state.json` remembers what is staged and how many install attempts a version has had, so
  a build that keeps failing is given up on instead of retried at every start.
"""

import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

import app_settings
import bundle
import db
import mac_app
import source_http
import update_manifest as um
import version
from updates import REPO, parse_version

log = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
MAX_REDIRECTS = 5
CHUNK = 1024 * 256
HEADROOM_BYTES = 100 * 1024 * 1024
MAX_ATTEMPTS = 2
FIRST_CHECK_SECONDS = 30
CHECK_EVERY_SECONDS = 24 * 60 * 60
RETRY_SECONDS = (15 * 60, 60 * 60, 6 * 60 * 60)
BUSY_RETRY_SECONDS = 10 * 60
SELF_CHECK_SECONDS = 180
MARKER_NAME = "started.json"
RESULT_NAME = "result.json"
STATE_NAME = "state.json"
HELPER_NAME = "update-helper" + (".exe" if sys.platform == "win32" else "")


class UpdateError(Exception):
    """An update step failed; the message is for the log and the status line."""


# ------------------------------------------------------------------ paths and state

def updates_dir():
    return db.DB_PATH.parent / "updates"


def _state_path():
    return updates_dir() / STATE_NAME


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_state():
    """The remembered state; anything unreadable is "nothing remembered"."""
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state):
    try:
        _write_json(_state_path(), state)
    except OSError as exc:
        log.warning("Could not save the update state (%s).", exc)


_lock = threading.Lock()
_status = {
    "state": "idle",
    "current": version.__version__,
    "latest": None,
    "notice": "",
    "url": None,
    "required": False,
    "progress": 0.0,
    "error": "",
    "checked_at": None,
}


def status():
    """What the page shows: a copy of the in-memory status plus the saved auto-apply choice."""
    with _lock:
        copy = dict(_status)
    copy["current"] = version.__version__
    copy["auto_apply"] = app_settings.auto_apply()
    return copy


def _set(**changes):
    with _lock:
        _status.update(changes)


def reset_for_tests():
    with _lock:
        _status.update(state="idle", current=version.__version__, latest=None, notice="", url=None, required=False,
                       progress=0.0, error="", checked_at=None)


# ------------------------------------------------------------------ where it may run

def enabled():
    """Background checking runs only in a packaged app, and tests can turn it off."""
    if um.testing_enabled() and os.environ.get("LIT_REVIEW_NO_UPDATE_THREAD"):
        return False
    return bundle.is_frozen() or um.testing_enabled()


def _base_url():
    """Where the manifest and zips come from. `LIT_REVIEW_UPDATE_BASE` (a loopback URL for a
    local fake release server) is honoured only under LIT_REVIEW_TESTING=1."""
    override = os.environ.get("LIT_REVIEW_UPDATE_BASE") if um.testing_enabled() else None
    if override:
        host = urlparse(override).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise UpdateError("the test update server must be on this computer")
        return override.rstrip("/")
    return None


def manifest_url(name):
    base = _base_url()
    return f"{base}/{name}" if base else f"https://github.com/{REPO}/releases/latest/download/{name}"


def asset_url(tag, name):
    base = _base_url()
    return f"{base}/{name}" if base else f"https://github.com/{REPO}/releases/download/{tag}/{name}"


def _host_ok(url):
    parsed = urlparse(url)
    if _base_url() and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return True
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def _open(url, headers=None, stream=False):
    """GET `url`, following redirects by hand so every hop is checked against the allowlist."""
    for _ in range(MAX_REDIRECTS + 1):
        if not _host_ok(url):
            raise UpdateError(f"refusing to fetch from {urlparse(url).hostname}")
        try:
            response = source_http.get("GitHub", url, headers=dict(headers or {}), stream=stream, allow_redirects=False)
        except source_http.SourceError as exc:
            raise UpdateError(str(exc)) from exc
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise UpdateError("a redirect had no destination")
            url = urljoin(url, location)
            continue
        return response
    raise UpdateError("too many redirects")


# ------------------------------------------------------------------ fetching the manifest

def fetch_manifest(running=None):
    """The verified Manifest for a release newer than the running version, or UpdateError /
    ManifestError. Asks github.com directly (not the rate-limited API)."""
    running = running or version.__version__
    raw = _fetch_small(manifest_url("update-manifest.json"), um.MAX_MANIFEST_BYTES)
    signature = _fetch_small(manifest_url("update-manifest.json.sig"), 4096)
    return um.load(raw, signature, running), raw


def _fetch_small(url, limit):
    response = _open(url)
    try:
        if response.status_code == 404:
            raise um.ManifestError("the latest release has no signed update manifest")
        if response.status_code != 200:
            raise UpdateError(f"{urlparse(url).path.rsplit('/', 1)[-1]} answered {response.status_code}")
        body = response.content
    finally:
        response.close()
    if len(body) > limit:
        raise UpdateError("a reply was larger than expected")
    return body


# ------------------------------------------------------------------ downloading

def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_free_space(directory, asset):
    directory.mkdir(parents=True, exist_ok=True)
    need = asset.size + asset.unpacked_size + HEADROOM_BYTES
    free = shutil.disk_usage(directory).free
    if free < need:
        raise UpdateError(f"not enough free disk space for the update ({need // 2**20} MB needed)")


def download(asset, tag, directory, *, progress=lambda fraction: None, cancelled=lambda: False):
    """The zip in `directory`, downloaded (resuming a partial file) and verified against the signed
    size and SHA-256. A bad file is deleted so the next try starts clean."""
    directory.mkdir(parents=True, exist_ok=True)
    final, part = directory / asset.name, directory / (asset.name + ".part")
    if final.exists() and final.stat().st_size == asset.size and _sha256_of(final) == asset.sha256:
        return final
    final.unlink(missing_ok=True)

    have = part.stat().st_size if part.exists() else 0
    if have > asset.size:
        part.unlink()
        have = 0
    if have < asset.size:
        response = _open(asset_url(tag, asset.name), {"Range": f"bytes={have}-"} if have else None, stream=True)
        try:
            if response.status_code == 206 and have:
                mode = "ab"
            elif response.status_code == 200:
                mode, have = "wb", 0
            else:
                if response.status_code == 416:
                    part.unlink(missing_ok=True)
                raise UpdateError(f"the download answered {response.status_code}")
            with open(part, mode) as out:
                for chunk in response.iter_content(CHUNK):
                    if cancelled():
                        raise UpdateError("the download was cancelled")
                    have += len(chunk)
                    if have > asset.size:
                        out.close()
                        part.unlink(missing_ok=True)
                        raise UpdateError("the download was larger than the signed size")
                    out.write(chunk)
                    progress(have / asset.size)
        except source_http.SourceError as exc:
            raise UpdateError(str(exc)) from exc
        except OSError as exc:
            raise UpdateError(f"the download stopped ({exc})") from exc
        finally:
            response.close()
    if part.stat().st_size != asset.size:
        raise UpdateError("the download stopped early; it will resume next time")
    if _sha256_of(part) != asset.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("the download did not match its signed checksum")
    os.replace(part, final)
    return final


# ------------------------------------------------------------------ the install layout

def exe_relative(install):
    return Path(sys.executable).relative_to(install)


def _can_write(folder):
    """Whether files can really be created in `folder` (os.access says yes for a Windows folder
    such as Program Files that a standard user still cannot change)."""
    try:
        with tempfile.TemporaryDirectory(dir=folder, prefix=".lit-review-probe-"):
            return True
    except OSError:
        return False


def install_layout(executable=None, plat=None):
    """(install folder, executable path relative to it), or raises UpdateError with a reason a
    person can act on ("move it to ..."). The folder must be one the app can replace."""
    executable = Path(executable or sys.executable)
    plat = plat or sys.platform
    if plat == "win32":
        install = executable.parent
        if len(str(install)) > 150:
            raise UpdateError("the folder path is too long to update safely; move Lit Review closer to the top of a drive")
        if not (install / "_internal").is_dir():
            raise UpdateError("this copy is not laid out the way the updater expects")
    elif plat == "darwin":
        if len(executable.parents) < 3 or executable.parents[2].suffix != ".app":
            raise UpdateError("this copy is not laid out the way the updater expects")
        install = executable.parents[2]
        if "AppTranslocation" in str(install) or mac_app.running_from_read_only_volume(str(install)):
            raise UpdateError("Lit Review is running from a read-only place; drag it into your Applications folder first")
    else:
        raise UpdateError("updating is only available in the Windows and Mac apps")
    if not _can_write(install.parent):
        raise UpdateError("Lit Review is in a folder you cannot change; move it somewhere you can (such as your Documents folder)")
    return install, executable.relative_to(install)


# ------------------------------------------------------------------ staging

def safe_members(zip_path, max_unpacked):
    """The zip's single top-level folder name, after checking every entry stays inside it."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError("the downloaded file is not a valid zip") from exc
    with archive:
        top = set()
        total = 0
        for info in archive.infolist():
            name = info.filename
            posix = PurePosixPath(name)
            if (not name or "\\" in name or ":" in name or posix.is_absolute() or ".." in posix.parts
                    or any(ch in name for ch in "\0\r\n")):
                raise UpdateError(f"the zip holds an unsafe path ({name!r})")
            if posix.parts[0] != "__MACOSX":  # resource-fork sidecars `ditto -c --sequesterRsrc` may add
                top.add(posix.parts[0])
            total += info.file_size
            if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK and sys.platform == "win32":
                raise UpdateError("the zip holds a link, which a Windows build never does")
        if len(top) != 1:
            raise UpdateError("the zip does not hold exactly one top-level folder")
        if total > max_unpacked * 1.1 + 1024 * 1024:
            raise UpdateError("the zip unpacks to more than its signed size")
        return top.pop()


def _extract(zip_path, destination):
    if sys.platform == "darwin":
        # ditto keeps permissions, symlinks and the ad hoc signature, which Python's zipfile would lose.
        done = subprocess.run(["ditto", "-x", "-k", str(zip_path), str(destination)], capture_output=True, text=True, timeout=600)
        if done.returncode:
            raise UpdateError(f"ditto could not unpack the update: {done.stderr.strip()[:200]}")
    else:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(destination)


def self_check(executable, expected_version):
    """Run the staged build's own `--self-check` (no network, no keys, no data folder) and require
    it to pass and to report the expected version, so a broken or wrong build is never installed."""
    report = Path(tempfile.mkdtemp(prefix="lit-review-selfcheck-")) / "report.json"
    env = {**os.environ, "LIT_REVIEW_SELFCHECK_FILE": str(report), "LIT_REVIEW_NO_DIALOG": "1"}
    try:
        subprocess.run([str(executable), "--self-check"], env=env, capture_output=True, timeout=SELF_CHECK_SECONDS)
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"the new version could not be checked ({type(exc).__name__})") from exc
    finally:
        shutil.rmtree(report.parent, ignore_errors=True)
    if not data.get("ok"):
        raise UpdateError("the new version failed its own self-check")
    if data.get("version") != expected_version:
        raise UpdateError(f"the downloaded build is version {data.get('version')}, not {expected_version}")


def verify_mac_signature(app):
    """`codesign --verify` on an unpacked Mac app: the ad hoc signature must have survived the
    download and unpacking, or Apple Silicon would refuse to run it."""
    done = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, timeout=120)
    if done.returncode:
        raise UpdateError("the new app's signature did not verify")


def stage(zip_path, asset, expected_version, install, exe_rel, *, check=self_check, extract=None, verify=None):
    """Unpack the zip next to `install` as `<install>.new` and prove it. Returns that folder."""
    top = safe_members(zip_path, asset.unpacked_size)
    parent = install.parent
    new = parent / (install.name + ".new")
    work = parent / (install.name + ".staging")
    for leftover in (new, work):
        shutil.rmtree(leftover, ignore_errors=True)
    work.mkdir()
    try:
        (extract or _extract)(zip_path, work)
        unpacked = work / top
        if not (unpacked / exe_rel).is_file():
            raise UpdateError("the update does not hold the program file where it is expected")
        os.replace(unpacked, new)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(new, ignore_errors=True)
        raise
    shutil.rmtree(work, ignore_errors=True)
    try:
        if verify is not None:
            verify(new)
        elif sys.platform == "darwin":
            verify_mac_signature(new)
        check(new / exe_rel, expected_version)
    except Exception:
        shutil.rmtree(new, ignore_errors=True)
        raise
    return new


# ------------------------------------------------------------------ one pass

def _staged_for(state, release):
    staged = state.get("staged")
    return isinstance(staged, dict) and staged.get("version") == release and Path(str(staged.get("dir", ""))).is_dir()


def discard_staged(state):
    """Forget (and delete) the staged copy."""
    staged = state.pop("staged", None)
    if isinstance(staged, dict) and staged.get("dir"):
        shutil.rmtree(staged["dir"], ignore_errors=True)


def prune_downloads(directory, keep_name=None):
    """Delete downloaded zips and partial files, except the one being resumed (`keep_name`)."""
    if not directory.exists():
        return
    for item in directory.glob("*.zip*"):
        if keep_name is None or item.name not in (keep_name, keep_name + ".part"):
            item.unlink(missing_ok=True)


_check_lock = threading.Lock()


def check_once(*, jobs_running=lambda: False, cancelled=lambda: False):
    """One full pass: ask, and if there is a newer signed release, download and stage it.
    Returns the seconds to wait before another pass is useful, or None for the normal interval.
    Only one pass runs at a time; a second call while one is running does nothing."""
    if not _check_lock.acquire(blocking=False):
        return None
    try:
        return _check_pass(jobs_running, cancelled)
    finally:
        _check_lock.release()


def check_now(jobs_running=lambda: False):
    """"Check now": start a pass on its own thread. False if one is already running."""
    if _check_lock.locked():
        return False
    threading.Thread(target=check_once, kwargs={"jobs_running": jobs_running}, name="update-check-now", daemon=True).start()
    return True


def _check_pass(jobs_running, cancelled):
    if _status["state"] == "applying":
        return None  # the helper is about to swap the staged copy: do not re-stage or discard it
    running = version.__version__
    _set(error="")
    try:
        manifest, _raw = fetch_manifest(running)
    except um.ManifestError as exc:
        # Not newer, unsigned, or malformed: nothing to offer. Logged only when it is not the plain "not newer".
        if "not newer" not in str(exc):
            log.warning("No usable update manifest: %s", exc)
        _set(state="idle", latest=None, notice="", required=False, checked_at=time.time())
        return None
    except UpdateError as exc:
        log.warning("The update check failed: %s", exc)
        _set(error=str(exc), checked_at=time.time())
        return RETRY_SECONDS[0]

    required = um.is_required(manifest, running)
    page = f"https://github.com/{REPO}/releases/tag/{manifest.tag}"
    _set(latest=manifest.version, notice=manifest.notice, url=page, required=required, checked_at=time.time(), state="available")

    state = load_state()
    if state.get("failed") == manifest.version:
        _set(state="failed", error="This update could not be installed. You can download it yourself.")
        return None
    if _staged_for(state, manifest.version):
        _set(state="staged", progress=1.0)
        return None

    asset = um.asset_for(manifest)
    if asset is None:
        _set(state="unsupported", error="There is no download for this computer.")
        return None
    try:
        install, exe_rel = install_layout()
    except UpdateError as exc:
        _set(state="unsupported", error=str(exc))
        return None
    if jobs_running():
        return BUSY_RETRY_SECONDS  # a search or grading run is using the connection and the disk

    discard_staged(state)  # an older staged copy is superseded
    directory = updates_dir()
    prune_downloads(directory, keep_name=asset.name)  # other versions' files; this one's partial is resumed
    try:
        check_free_space(directory, asset)
        _set(state="downloading", progress=0.0)
        zip_path = download(asset, manifest.tag, directory, progress=lambda f: _set(progress=f), cancelled=cancelled)
        new = stage(zip_path, asset, manifest.version, install, exe_rel)
    except (UpdateError, OSError) as exc:
        log.warning("Could not prepare the update: %s", exc)
        _set(state="available", error=str(exc), progress=0.0)
        return RETRY_SECONDS[0]
    state["staged"] = {"version": manifest.version, "dir": str(new), "min_version": manifest.min_version,
                       "exe": str(exe_rel), "install": str(install)}
    save_state(state)
    prune_downloads(directory)  # the unpacked copy is what is used from here
    _set(state="staged", progress=1.0, error="")
    return None


_thread = None
_stop = threading.Event()


def start_background(jobs_running=lambda: False):
    """Start the checking thread (once). Returns it, or None where updating is off."""
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return _thread
    _stop.clear()

    def loop():
        delay, failures = FIRST_CHECK_SECONDS, 0
        while not _stop.wait(delay):
            try:
                wait = check_once(jobs_running=jobs_running, cancelled=_stop.is_set)
            except Exception:  # noqa: BLE001 - a bug here must never take the app down
                log.exception("The update check crashed.")
                wait = RETRY_SECONDS[0]
            if wait is None:
                failures, delay = 0, CHECK_EVERY_SECONDS
            elif wait == BUSY_RETRY_SECONDS:
                delay = wait  # busy is not a failure
            else:
                delay = RETRY_SECONDS[min(failures, len(RETRY_SECONDS) - 1)]
                failures += 1

    _thread = threading.Thread(target=loop, name="update-check", daemon=True)
    _thread.start()
    return _thread


def stop_background():
    _stop.set()


# ------------------------------------------------------------------ applying

def helper_command():
    """The program that does the swap: the packaged `update-helper`, or from source the script run
    by this Python (used by tests)."""
    packaged = bundle.resource_path(HELPER_NAME)
    if packaged.is_file():
        return [str(packaged)]
    script = Path(__file__).resolve().parent.parent / "packaging" / "update_helper.py"
    if script.is_file():
        return [sys.executable, str(script)]
    raise UpdateError("the update helper is missing from this copy")


def launch_helper(staged, *, popen=subprocess.Popen):
    """Copy the helper out of the install folder (it is about to be renamed) and start it,
    detached, with an argument list. The caller must then quit."""
    install, new = Path(staged["install"]), Path(staged["dir"])
    command = helper_command()
    scratch = Path(tempfile.mkdtemp(prefix="lit-review-update-"))
    program = Path(command[-1])
    copy = scratch / program.name
    shutil.copy2(program, copy)
    copy.chmod(copy.stat().st_mode | stat.S_IXUSR)
    command = [*command[:-1], str(copy)]
    directory = updates_dir()
    args = [
        *command,
        "--install", str(install),
        "--new", str(new),
        "--old", str(install.with_name(install.name + ".old")),
        "--exe", str(staged["exe"]),
        "--pid", str(os.getpid()),
        "--marker", str(directory / MARKER_NAME),
        "--version", str(staged["version"]),
        "--result", str(directory / RESULT_NAME),
    ]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(scratch)}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    try:
        if db.DB_PATH.exists():
            directory.mkdir(parents=True, exist_ok=True)
            for older in directory.glob("before-update-*.db"):
                older.unlink(missing_ok=True)  # only the newest is kept
            db.write_backup(directory / f"before-update-{version.__version__}.db")
    except Exception as exc:  # noqa: BLE001 - a backup that cannot be made must not stop an update
        log.warning("Could not back up the database before updating: %s", exc)
    return popen(args, **kwargs)


def usable_staged(state, running):
    """The staged entry if it is newer than `running`, still on disk and not given up on."""
    staged = state.get("staged")
    if not isinstance(staged, dict):
        return None
    theirs, mine = parse_version(staged.get("version")), parse_version(running)
    if not theirs or not mine or theirs <= mine:
        return None
    if not Path(str(staged.get("dir", ""))).is_dir() or state.get("failed") == staged["version"]:
        return None
    return staged


def should_apply(staged, running, auto_apply):
    """Install a staged update without being asked: the setting is on, or the running version is
    older than the release's `min_version`."""
    if auto_apply:
        return True
    floor = parse_version(staged.get("min_version")) if staged.get("min_version") else None
    mine = parse_version(running)
    return bool(floor and mine and mine < floor)


def apply_at_launch(*, running=None, launch=launch_helper):
    """Called from main() once this copy holds the instance lock and before it serves anything:
    if an update is staged and due, start the helper and return True (the caller exits). Counts the
    attempt first, and gives up on a version after MAX_ATTEMPTS."""
    running = running or version.__version__
    if not bundle.is_frozen() and not um.testing_enabled():
        return False
    state = load_state()
    staged = usable_staged(state, running)
    if not staged or not should_apply(staged, running, app_settings.auto_apply()):
        return False
    attempts = state.setdefault("attempts", {})
    if attempts.get(staged["version"], 0) >= MAX_ATTEMPTS:
        state["failed"] = staged["version"]
        discard_staged(state)
        save_state(state)
        return False
    attempts[staged["version"]] = attempts.get(staged["version"], 0) + 1
    save_state(state)
    try:
        launch(staged)
    except (OSError, UpdateError) as exc:
        log.warning("Could not start the update helper: %s", exc)
        return False
    return True


def start_apply(*, launch=launch_helper):
    """The "Install and restart" button: start the helper for what is staged. The caller (the
    route) has quiesced the server and quits afterwards. Raises UpdateError if nothing is ready."""
    state = load_state()
    staged = usable_staged(state, version.__version__)
    if not staged:
        raise UpdateError("There is no update ready to install.")
    attempts = state.setdefault("attempts", {})
    attempts[staged["version"]] = attempts.get(staged["version"], 0) + 1
    save_state(state)
    _set(state="applying")
    try:
        return launch(staged)
    except (OSError, UpdateError) as exc:
        _set(state="staged", error=str(exc))
        raise UpdateError(f"The update could not be started ({exc}).") from exc


# ------------------------------------------------------------------ after a restart

def write_started_marker(running=None):
    """Called once the server is up and the instance file is written: if this copy is the update
    the helper is waiting for, say so (the helper rolls back without it)."""
    running = running or version.__version__
    staged = load_state().get("staged")
    if isinstance(staged, dict) and staged.get("version") == running:
        try:
            _write_json(updates_dir() / MARKER_NAME, {"version": running})
        except OSError as exc:
            log.warning("Could not write the update marker: %s", exc)


def take_result(running=None):
    """What the last install attempt did, as a message for the user (or None), and tidy up.
    Called after the app has started successfully."""
    running = running or version.__version__
    path = updates_dir() / RESULT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    state = load_state()
    message = None
    if isinstance(data, dict):
        status_text, wanted = data.get("status"), data.get("version")
        if status_text == "installed" and wanted == running:
            staged = state.get("staged")
            if isinstance(staged, dict) and staged.get("version") == wanted:
                state.pop("staged")  # not a newer release staged since
            state.get("attempts", {}).pop(wanted, None)
            state.pop("failed", None)
            message = None
        elif status_text in ("not_installed", "rolled_back", "stranded"):
            reason = data.get("reason") or "The update could not be installed."
            message = f"The update to {wanted} could not be installed, so you are still on version {running}. {reason}"
            if state.get("attempts", {}).get(wanted, 0) >= MAX_ATTEMPTS:
                state["failed"] = wanted
                discard_staged(state)
        save_state(state)
        path.unlink(missing_ok=True)
    return message


def note_failure(message):
    """Show a failed install on the page (state `failed`, with the message and the manual link)."""
    _set(state="failed", error=message, url=_status["url"] or f"https://github.com/{REPO}/releases/latest")


def cleanup_stale(install=None):
    """Remove what an interrupted update left behind (partial downloads, helper copies, old and
    failed folders) once the app is up. Never touches a staged copy that is still wanted."""
    directory = updates_dir()
    if directory.exists():
        for part in directory.glob("*.part"):
            if time.time() - part.stat().st_mtime > 3 * 24 * 3600:
                part.unlink(missing_ok=True)
        # The marker is NOT removed here: main() has just written it for a waiting helper, and the
        # helper deletes any stale one itself before it starts the new copy.
    for scratch in Path(tempfile.gettempdir()).glob("lit-review-update-*"):
        try:  # copies of the helper that earlier updates ran from (it cannot delete itself)
            if time.time() - scratch.stat().st_mtime > 24 * 3600:
                shutil.rmtree(scratch, ignore_errors=True)
        except OSError:
            pass
    try:
        install = install or install_layout()[0]
    except UpdateError:
        return
    for suffix in (".old", ".failed", ".staging"):
        leftover = install.with_name(install.name + suffix)
        if leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)
    state = load_state()
    if not usable_staged(state, version.__version__):
        leftover = install.with_name(install.name + ".new")
        if leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)
        if state.pop("staged", None) is not None:
            save_state(state)
