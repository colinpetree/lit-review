"""Cross-platform encrypted local-file storage for user-supplied API keys.

Deliberately not the OS-native keyring/credential manager (Windows Credential
Manager / macOS Keychain / Linux Secret Service via the `keyring` package):
those diverge enough across platforms - Secret Service in particular is often
unavailable on headless/minimal Linux installs - that one encrypted-file
format used identically on every OS beats integrating with each OS's native
store. See PLAN.md's Architecture section.
"""

import json
import os
import stat
import threading
from pathlib import Path

import platformdirs
from cryptography.fernet import Fernet
from filelock import FileLock

APP_NAME = "lit-review"
CONFIG_DIR = Path(platformdirs.user_config_dir(APP_NAME))
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


def _file_lock():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return FileLock(str(LOCK_FILE))


def _restrict(path):
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # best-effort - not every filesystem honors POSIX perms


def _fernet():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        _restrict(KEY_FILE)
    return Fernet(key)


def _load_store():
    if not STORE_FILE.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(STORE_FILE.read_bytes()).decode())
    except Exception:
        # Corrupt store or key/store mismatch - treat as empty rather than crash.
        return {}


def _save_store(data):
    STORE_FILE.write_bytes(_fernet().encrypt(json.dumps(data).encode()))
    _restrict(STORE_FILE)


def get_key(name):
    """Look up a stored credential by provider name (e.g. "anthropic"). Falls
    back to the conventional env var (e.g. ANTHROPIC_API_KEY) for dev
    convenience when nothing has been saved via the settings UI yet."""
    with _LOCK, _file_lock():
        store = _load_store()
    if name in store:
        return store[name]
    return os.environ.get(f"{name.upper()}_API_KEY")


def set_key(name, value):
    with _LOCK, _file_lock():
        store = _load_store()
        store[name] = value
        _save_store(store)


def delete_key(name):
    with _LOCK, _file_lock():
        store = _load_store()
        if store.pop(name, None) is not None:
            _save_store(store)


def has_key(name):
    return bool(get_key(name))
