"""Telling the user things when there is no console.

The packaged app has no console window (it lives in the tray), so `sys.stdout` and
`sys.stderr` are None: a message printed there is silently dropped, and a launch
that failed would look like nothing happened. From source, or from a terminal,
there are streams and messages go there as they always did.

Dialogs are the operating system's own (a message box on Windows, `osascript` on
macOS), never a GUI toolkit, so nothing here fights the tray's event loop. There
is no Linux target; there a message goes to stderr.

`LIT_REVIEW_NO_DIALOG=1` turns dialogs off (tests and CI).
"""

import os
import subprocess
import sys

def _detect_console():
    """Is there a console to print to? Windows gives a windowed build no streams at
    all (None), but a macOS .app started from Finder has them, pointing at nowhere.
    So a packaged build counts as having a console only if it was started from a
    terminal (stderr is a terminal)."""
    stream = sys.stderr
    if stream is None:
        return False
    if getattr(sys, "frozen", False):
        try:
            return bool(stream.isatty())
        except (AttributeError, ValueError):
            return False
    return True


# Taken at import, before ensure_streams() replaces a missing stream.
_HAS_CONSOLE = _detect_console()


def has_console():
    return _HAS_CONSOLE


def ensure_streams():
    """Give a windowed build harmless stdout/stderr, since some library code (and
    logging's last-resort handler) writes to them directly."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _dialogs_enabled():
    return not os.environ.get("LIT_REVIEW_NO_DIALOG")


def _mac_dialog(title, message, buttons, default, icon):
    """Run an AppleScript dialog; the text travels as arguments, never inside the
    script, so it cannot be mistaken for AppleScript. Returns the label of the
    button clicked, or None if the dialog was cancelled or could not be shown."""
    script = [
        "on run argv",
        "set theButtons to {" + ", ".join(f'"{b}"' for b in buttons) + "}",
        "set answer to display dialog (item 1 of argv) with title (item 2 of argv) "
        f'buttons theButtons default button "{default}" with icon {icon}',
        "return button returned of answer",
        "end run",
    ]
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    args += [message, title]
    result = subprocess.run(args, capture_output=True, text=True, timeout=600)
    return result.stdout.strip() if result.returncode == 0 else None


def show_error(title, message):
    """Tell the user something went wrong: on the console if there is one, else in a
    dialog. Always returns (it never raises, so a failed dialog cannot hide the
    original problem)."""
    if _HAS_CONSOLE:
        print(message, file=sys.stderr)
        return
    if not _dialogs_enabled():
        return
    try:
        if sys.platform == "win32":
            import ctypes

            # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x0 | 0x10 | 0x10000 | 0x40000)
        elif sys.platform == "darwin":
            _mac_dialog(title, message, ["OK"], "OK", "stop")
    except Exception:  # noqa: BLE001 - nothing more can be done to show it
        pass


def confirm(title, message, yes_label="Quit", default_yes=False):
    """Ask a yes/no question in a dialog. True for yes. With no way to ask (a
    console run, dialogs off, an error) the answer is yes: the caller only asks
    before something the user already chose to do."""
    if _HAS_CONSOLE or not _dialogs_enabled():
        return True
    try:
        if sys.platform == "win32":
            import ctypes

            # MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2 | MB_SETFOREGROUND | MB_TOPMOST
            flags = 0x4 | 0x20 | (0x0 if default_yes else 0x100) | 0x10000 | 0x40000
            return ctypes.windll.user32.MessageBoxW(0, message, title, flags) == 6
        if sys.platform == "darwin":
            answer = _mac_dialog(title, message, ["Cancel", yes_label], yes_label if default_yes else "Cancel", "caution")
            return answer == yes_label
    except Exception:  # noqa: BLE001
        pass
    return True
