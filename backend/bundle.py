"""Where the app's own files are, whether it runs from source or as a packaged
(PyInstaller) build. The packaged app unpacks next to its executable and
PyInstaller points `sys._MEIPASS` at that folder; from source it is this one."""

import sys
from pathlib import Path


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts):
    """A file or folder shipped with the app, such as `static` or `tray.png`."""
    base = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)
    return base.joinpath(*parts)
