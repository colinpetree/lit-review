"""Small app settings kept on disk, so the tray and the background update thread can read
them with no browser open (the Settings page used to keep its choices in the browser).

One file, `settings.json` in the config folder, replaced in one step so a crash leaves the old
copy. A missing, unreadable or damaged file means the defaults, and is never an error.
"""

import json
import logging
import os
import threading

import credentials

log = logging.getLogger(__name__)

DEFAULTS = {"auto_apply": False}
_lock = threading.Lock()


def _path():
    return credentials.CONFIG_DIR / "settings.json"


def load():
    """All settings, defaults filled in for anything missing or of the wrong type."""
    settings = dict(DEFAULTS)
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as exc:
        log.warning("The settings file could not be read (%s); using the defaults.", exc)
        return settings
    if isinstance(data, dict):
        for name, default in DEFAULTS.items():
            if isinstance(data.get(name), type(default)):
                settings[name] = data[name]
    return settings


def auto_apply():
    return load()["auto_apply"]


def save(**changes):
    """Merge `changes` into the saved settings and return them all. Unknown names and values
    of the wrong type raise ValueError."""
    for name, value in changes.items():
        if name not in DEFAULTS or not isinstance(value, type(DEFAULTS[name])):
            raise ValueError(f"bad setting {name!r}")
    with _lock:
        settings = load()
        settings.update(changes)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return settings
