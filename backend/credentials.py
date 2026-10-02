"""Cross-platform encrypted local-file storage for user-supplied API keys.

Deliberately not the OS-native keyring/credential manager (Windows Credential
Manager / macOS Keychain / Linux Secret Service via the `keyring` package):
those diverge enough across platforms - Secret Service in particular is often
unavailable on headless/minimal Linux installs - that one encrypted-file
format used identically on every OS beats integrating with each OS's native
store. See PLAN.md's Architecture section.

What this protects against: the keys are not readable as text in a backup,
a synced folder or a screenshot of the folder. It is not protection from
other software running as the same user, because the Fernet key sits in the
same folder as the encrypted file. File permissions are the real barrier: the
POSIX mode is set to owner-only, and on Windows (where chmod does nothing
useful) the user profile folder's own access rules apply.

Files are written atomically (temp file, then replace), and a store that can't
be read is never silently overwritten: it is renamed aside first (see
set_key).
"""

import json
import logging
import os
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path

import platformdirs
from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock

log = logging.getLogger(__name__)

APP_NAME = "lit-review"
# LIT_REVIEW_CONFIG_DIR is for development and tests only, so they never touch
# the real saved keys.
CONFIG_DIR = Path(os.environ.get("LIT_REVIEW_CONFIG_DIR") or platformdirs.user_config_dir(APP_NAME))
KEY_FILE = CONFIG_DIR / "credentials.key"
STORE_FILE = CONFIG_DIR / "credentials.enc"
LOCK_FILE = CONFIG_DIR / "credentials.lock"

# The Flask app runs threaded, so two settings requests could otherwise race
# on the store file's read-modify-write cycle (e.g. a concurrent save and
# delete) and one write could silently clobber the other. _LOCK covers
# threads within this process; _file_lock() (an OS-level advisory lock via
# `filelock`, working identically on Windows/Mac/Linux) covers the same race
# across separate processes, in case two copies of the app ever run at once.
_LOCK = threading.Lock()

# Whether the "keys can't be read" warning was already logged, so the Settings
# page polling for status doesn't repeat it every time.
_unreadable_logged = False


class CredentialStoreError(Exception):
    """Saved keys exist but can't be read: the key file is missing or damaged,
    or the store doesn't decrypt with it."""


def _file_lock():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return FileLock(str(LOCK_FILE))


def _restrict(path):
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # best-effort - not every filesystem honors POSIX perms


def _write_atomic(path, data):
    """Replace `path` with `data` in one step, so a crash mid-write leaves the
    old file intact instead of a truncated one."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    _restrict(tmp)
    os.replace(tmp, path)


def _read_key():
    """The Fernet key from the key file. Raises CredentialStoreError if the file
    is missing or doesn't hold a valid key."""
    try:
        raw = KEY_FILE.read_bytes().strip()
    except FileNotFoundError as exc:
        raise CredentialStoreError("The key file is missing.") from exc
    except OSError as exc:
        raise CredentialStoreError(f"The key file can't be read: {exc.strerror or exc}") from exc
    try:
        Fernet(raw)
    except (ValueError, TypeError) as exc:
        raise CredentialStoreError("The key file is damaged.") from exc
    return raw


def _create_key():
    """Make the key file, never overwriting one that already exists (another
    process may have just made it; its key is used instead). Created owner-only
    from the start, so there is no moment when it is readable by others."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(KEY_FILE, flags, 0o600)
    except FileExistsError:
        return _read_key()
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
        handle.flush()
        os.fsync(handle.fileno())
    return key


def _key_for_saving():
    return _read_key() if KEY_FILE.exists() else _create_key()


def _load_store():
    """The saved keys as {provider: key}: {} if none were ever saved. Raises
    CredentialStoreError if a store exists but can't be read, which must never
    be treated as "no keys" by anything that goes on to write."""
    if not STORE_FILE.exists():
        return {}
    key = _read_key()
    try:
        data = json.loads(Fernet(key).decrypt(STORE_FILE.read_bytes()).decode())
    except OSError as exc:
        raise CredentialStoreError(f"The saved keys can't be read: {exc.strerror or exc}") from exc
    except (InvalidToken, ValueError) as exc:  # a bad token, bad UTF-8 or bad JSON
        raise CredentialStoreError("The saved keys can't be decrypted with the key file.") from exc
    if not isinstance(data, dict):
        raise CredentialStoreError("The saved keys are in an unexpected format.")
    return data


def _load_or_report():
    """Like _load_store, for readers: an unreadable store counts as no keys (the
    environment-variable fallback still works) and is logged once."""
    global _unreadable_logged
    try:
        store = _load_store()
    except CredentialStoreError as exc:
        if not _unreadable_logged:
            log.warning("Saved API keys could not be read: %s", exc)
            _unreadable_logged = True
        return {}
    _unreadable_logged = False
    return store


def _quarantine():
    """Rename the store and key file aside (never delete them), so the user or a
    developer can still recover from the copies."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for path in (STORE_FILE, KEY_FILE):
        if path.exists():
            aside = path.with_name(f"{path.name}.corrupt-{stamp}")
            os.replace(path, aside)
            log.warning("Moved unreadable %s to %s", path.name, aside.name)


def get_key(name):
    """Look up a stored credential by provider name (e.g. "anthropic"). Falls
    back to the conventional env var (e.g. ANTHROPIC_API_KEY) for dev
    convenience when nothing has been saved via the settings UI yet."""
    with _LOCK, _file_lock():
        store = _load_or_report()
    if name in store:
        return store[name]
    return os.environ.get(f"{name.upper()}_API_KEY")


def set_key(name, value):
    with _LOCK, _file_lock():
        try:
            store = _load_store()
            key = _key_for_saving()
        except CredentialStoreError:
            # Saving over a store that can't be read would destroy every other
            # saved key for good. Move it aside and start a fresh one instead.
            _quarantine()
            store = {}
            key = _create_key()
        store[name] = value
        _write_atomic(STORE_FILE, Fernet(key).encrypt(json.dumps(store).encode()))


def delete_key(name):
    with _LOCK, _file_lock():
        try:
            store = _load_store()
            key = _read_key() if store else None
        except CredentialStoreError:
            return  # nothing readable to remove the key from
        if store.pop(name, None) is not None:
            _write_atomic(STORE_FILE, Fernet(key).encrypt(json.dumps(store).encode()))


def has_key(name):
    return bool(get_key(name))


def store_error():
    """Whether saved keys exist but can't be read, for the Settings page to say
    so instead of showing every key as missing."""
    with _LOCK, _file_lock():
        try:
            _load_store()
        except CredentialStoreError:
            return True
    return False
