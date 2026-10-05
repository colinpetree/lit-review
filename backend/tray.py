"""The tray (Windows) / menu-bar (macOS) icon of the packaged app.

It is the app's only visible part once the browser tab is closed: it shows that
Lit Review is running and has the way to open it again and to quit. `run()`
blocks on the calling thread until Quit, and must be the main thread (macOS
requires its event loop there); the web server runs on another thread.

Everything is passed in as functions, so this file knows nothing about Flask:
    open_app()        open the browser on the running app
    open_logs()       show the log folder
    confirm_quit()    True to go ahead and quit (asks first if a job is running)
"""

import logging
import os
import subprocess
import sys
import time

import bundle
import mac_app

log = logging.getLogger(__name__)

TOOLTIP = "Lit Review (running)"


class TrayUnavailable(Exception):
    """The tray cannot be shown here (no display, missing backend)."""


def _icon_image():
    from PIL import Image, ImageDraw

    path = bundle.resource_path("tray.png")
    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        # Running from source without the built icons: a plain stand-in.
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(image).rounded_rectangle((4, 4, 59, 59), radius=12, fill=(37, 99, 235, 255))
        return image


def open_folder(path):
    """Show a folder in the file manager (making it first if it is not there yet)."""
    os.makedirs(path, exist_ok=True)
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a folder we made, not user input
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


# Launching the app sends a reopen event on some macOS versions; the browser is being
# opened already then, so a reopen this soon after start is not a second double-click.
REOPEN_IGNORE_SECONDS = 4
_mac_handler_class = None


def register_reopen(callback):
    """macOS only: call `callback` when the user double-clicks the app (or its Dock
    icon) while it is already running. Launch Services does not start a second
    copy of a running .app, it sends the running one a "reopen" Apple event, so
    without this a second double-click would do nothing at all (the hand-over
    that Windows relies on never runs). Returns the handler object, which the
    caller must keep alive, or None elsewhere or if it cannot be installed. Not
    testable off a Mac; check it by double-clicking the app twice."""
    global _mac_handler_class
    if sys.platform != "darwin":
        return None
    started = time.monotonic()
    try:
        import Foundation

        if _mac_handler_class is None:

            class ReopenHandler(Foundation.NSObject):
                callback = None

                def handleReopen_withReplyEvent_(self, event, reply):
                    if self.callback and time.monotonic() - started >= REOPEN_IGNORE_SECONDS:
                        self.callback()

            _mac_handler_class = ReopenHandler
        handler = _mac_handler_class.alloc().init()
        handler.callback = callback

        def code(text):
            return int.from_bytes(text.encode("ascii"), "big")

        manager = Foundation.NSAppleEventManager.sharedAppleEventManager()
        manager.setEventHandler_andSelector_forEventClass_andEventID_(
            handler, b"handleReopen:withReplyEvent:", code("aevt"), code("rapp")
        )
        return handler
    except Exception:  # noqa: BLE001 - the app works without it, only the second double-click does not
        log.warning("Could not listen for a second launch of the app", exc_info=True)
        return None


def _menu_template_path():
    """The macOS menu-bar picture (a plain cap on transparent), or None if it was not
    shipped (a source run without built icons), in which case the stock icon stays."""
    path = bundle.resource_path("trayTemplate.png")
    return path if path.is_file() else None


class Tray:
    def __init__(self, open_app, open_logs, confirm_quit):
        try:
            import pystray
        except Exception as exc:  # noqa: BLE001 - ImportError, or a backend that cannot load
            raise TrayUnavailable(str(exc)) from exc
        self._icon = None
        self._stopping = False
        self._reopen = None
        self._mac = None  # the macOS delegate, kept alive for the loop's life
        self._mac_actions = None
        self._open_app = open_app
        self._open_logs = open_logs
        self._confirm_quit = confirm_quit
        self._pystray = pystray

    def _quit(self, icon, item):
        if self._mac_actions is not None:
            # macOS runs this on the thread that drives the menu bar, so the question is
            # asked on another one (same path as Cmd+Q and the Dock's Quit).
            self._mac_actions.terminate_requested(False)
        elif self._confirm_quit():
            icon.stop()

    def run(self):
        pystray = self._pystray
        menu = pystray.Menu(
            pystray.MenuItem("Open Lit Review", lambda icon, item: self._open_app(), default=True),
            pystray.MenuItem("Open log folder", lambda icon, item: self._open_logs()),
            pystray.MenuItem("Quit", self._quit),
        )
        try:
            self._icon = pystray.Icon("lit-review", _icon_image(), TOOLTIP, menu)
        except Exception as exc:  # noqa: BLE001
            raise TrayUnavailable(str(exc)) from exc
        if sys.platform == "darwin":
            self._mac_actions = mac_app.MacActions(self._open_app, self._open_logs, self._confirm_quit, self.stop)
            self._mac = mac_app.install(self._mac_actions)
            if self._mac is None:  # could not be installed: keep the older Dock-click handling
                self._reopen = register_reopen(self._open_app)
        self._icon.run(setup=self._setup)

    def _setup(self, icon):
        icon.visible = True
        if sys.platform == "darwin":
            image = _menu_template_path()
            if image is not None:
                mac_app.set_menu_bar_image(icon, image)
        if self._stopping:  # stop() came before the loop was running
            icon.stop()

    def stop(self):
        """Ends run() from any thread (the server thread, when it dies)."""
        self._stopping = True
        if self._icon is not None:
            self._icon.stop()
