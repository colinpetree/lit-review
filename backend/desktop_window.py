"""The packaged app's own window (pywebview), so Lit Review opens like a desktop app instead of
in a browser tab.

How it behaves, like a chat app that lives in the tray:

* The window shows the same page the browser did (the private link, so it is signed in).
* Its close button **hides** it. The app keeps running (searches, grading and lookups carry
  on) and the tray icon (Windows) or the Dock and menu-bar icons (macOS) bring it back.
* Quit is in the tray menu (and Cmd+Q on a Mac). It asks first while work is running, then
  closes the window, which ends pywebview's event loop so `main()` cleans up as before.
* Windows signing out or shutting down is let through: a window that refused that close
  would make Windows say "Lit Review is preventing shutdown".

pywebview draws the page with the operating system's own web engine: WebView2 on Windows,
WKWebView on macOS. Where neither can be used (no WebView2 runtime), `available()` raises
`WindowUnavailable` and the app opens the browser as it did before. If the window is up but
the page never loads (WebView2 failed to start after all), the watchdog opens the browser.

The behaviour is in `DesktopShell`, plain Python tested anywhere with a stand-in window
(`tests/test_desktop_window.py`). The functions below it are the thin layer around pywebview
and, on Windows, the .NET objects it is built on; each is guarded so a failure there leaves
the app working.
"""

import importlib
import logging
import sys
import threading

log = logging.getLogger(__name__)

TITLE = "Lit Review"
WINDOW_SIZE = (1280, 860)
MIN_SIZE = (900, 600)
# Matches the page's light background, so the moment before the page is drawn is not a white flash.
# (The window stays hidden until the page has loaded anyway; this only covers a slow first paint.)
BACKGROUND = "#f9fafb"
# How long a shown window may take to load the page before the browser is opened instead.
LOAD_WATCHDOG_SECONDS = 20

# Only the renderers that run the app's page. On Windows pywebview falls back to Internet
# Explorer (MSHTML) when WebView2 is missing, which cannot run it, so that counts as no window.
SUPPORTED_RENDERERS = {"edgechromium", "wkwebview"}

FIRST_HIDE_TITLE = "Lit Review is still running"
FIRST_HIDE_MESSAGE = "It keeps working in the background. Click the tray icon to open it, or right-click it to quit."

# The right-click menu in the window (Windows): only the editing items, so text can be copied
# and pasted with the mouse. WebView2's full menu also has Back, Reload, Save as and Print, which
# make no sense in an app window. These are WebView2's documented item names.
EDIT_MENU_ITEMS = {
    "undo",
    "redo",
    "cut",
    "copy",
    "paste",
    "pasteAndMatchStyle",
    "selectAll",
    "copyLinkLocation",
    "copyImage",
    "emoji",
}


# Python functions handed to .NET events, held for the life of the process.
_KEEP_ALIVE = []


class WindowUnavailable(Exception):
    """No app window here: pywebview, its backend or a usable web engine is missing."""


class DesktopShell:
    """What the window does, with no pywebview in sight.

    window          has show(), hide(), restore(), destroy() (a pywebview Window, or a stand-in)
    open_browser()  open the app in the browser (the fallback, and the tray's "Open in browser")
    first_hide()    called once per install the first time the window is hidden (the tray notice)
    """

    def __init__(self, open_browser, first_hide=None, start_thread=None, watchdog_seconds=LOAD_WATCHDOG_SECONDS):
        self.window = None
        self._open_browser = open_browser
        self._first_hide = first_hide
        self._start_thread = start_thread or self._thread
        self._watchdog_seconds = watchdog_seconds
        self._lock = threading.Lock()
        self.shown = threading.Event()  # pywebview created the window: its calls work from now on
        self.loaded = threading.Event()  # the page loaded at least once
        self.quit_requested = threading.Event()
        self.quitting = False
        self.broken = False  # the page never loaded: the browser is used instead
        self.minimized = False
        self.native_close = False  # Windows: the Form's own closing handler decides (see on_native_closing)
        self._show_when_ready = False
        self._hid_once = False
        self._quit_done = False
        self._on_quit = []

    @staticmethod
    def _thread(target):
        threading.Thread(target=target, name="app-window", daemon=True).start()

    def attach(self, window):
        self.window = window

    def on_quit(self, callback):
        """Also run `callback` when the app quits (the Windows tray icon must be stopped)."""
        self._on_quit.append(callback)

    def has_window(self):
        """Whether a second launch can be shown this window (else it opens the browser)."""
        return self.window is not None and not self.broken and not self.quitting

    # --- events from pywebview -------------------------------------------------------------

    def on_shown(self):
        """The window exists (it starts hidden). From here on pywebview's calls do not wait."""
        self.shown.set()
        self._start_thread(self._watch_the_first_load)

    def on_loaded(self):
        """The page finished loading. The first time, the window appears (it was hidden so the
        user never sees an empty frame)."""
        first = not self.loaded.is_set()
        self.loaded.set()
        if first and not self.broken:
            self.show()

    def on_minimized(self):
        self.minimized = True

    def on_restored(self):
        self.minimized = False

    def on_closing(self):
        """pywebview's `closing` event: return False to keep the window open. The close button
        hides the window instead of closing it. While quitting, the close goes ahead. On Windows
        the decision is left to `on_native_closing`, which can see *why* the window is closing."""
        if self.quitting:
            return None
        if not self.native_close:
            self._call(self.window.hide)
            self._after_hide()
        return False

    def on_native_closing(self, user_closing):
        """Windows only, from the Form's own FormClosing (it runs after pywebview's, which has
        already said "cancel"). Returns True to keep the window (hidden), False to let it close.
        Only a person closing the window hides it; signing out, shutting down, Task Manager and
        our own quit let it close, or Windows would report the app as blocking the shutdown.

        A WinForms quirk, checked on Windows 10: once a close has been cancelled (hidden), the
        Form keeps reporting that "user closing" reason, so a later close from Task Manager also
        looks like the close button and only hides. Task Manager then ends the process itself
        after a few seconds, as for any program that does not close, which is safe (SQLite and
        the instance lock survive it). Sign-out and shutdown are always reported as such."""
        if self.quitting:
            return False
        if not user_closing:
            # Only allow it; change nothing. Windows asks every program before ending a session and
            # another one may still refuse, and then Lit Review carries on as it was. If the window
            # really closes, pywebview's loop ends and main() cleans up (calling quit()).
            log.info("Windows asked to close the window (sign-out, shutdown or Task Manager); allowing it")
            return False
        self._call(self.window.hide)
        self._after_hide()
        return True

    # --- what the tray, the Dock, a second launch and the quit paths call -----------------

    def show(self):
        """Bring the window back: un-minimize, show, bring to the front. Before the window exists
        it is remembered and done once it does. If the page never loaded, the browser instead."""
        if self.broken:
            self._open_browser()
            return
        with self._lock:
            if not self.shown.is_set() or not self.loaded.is_set():
                self._show_when_ready = True
                return

        def bring_back():
            if self.minimized:
                self._call(self.window.restore)
            self._call(self.window.show)

        self._start_thread(bring_back)

    def quit(self):
        """Quit now, without asking (the tray and Cmd+Q asked already through `confirm_quit`; an
        update install and a dead server do not ask). Closing the window ends pywebview's loop,
        and so `main()`. Safe to call more than once and from any thread; `main()` calls it again
        after the loop ends, so the tray icon is removed however the window went away."""
        with self._lock:
            if self._quit_done:
                return
            self._quit_done = True
            self.quitting = True
        self.quit_requested.set()
        for callback in self._on_quit:
            try:
                callback()
            except Exception:  # noqa: BLE001
                log.exception("Stopping part of the app failed")
        if self.window is None:
            return
        if self.shown.is_set():
            self._call(self.window.destroy)
        else:
            # Quitting before pywebview has made the window (the server died at once): close it
            # as soon as it exists, or its event loop would keep the process running.
            def close_once_made():
                if self.shown.wait(60):
                    self._call(self.window.destroy)

            self._start_thread(close_once_made)

    # --- inside ----------------------------------------------------------------------------

    def _after_hide(self):
        if self._hid_once:
            return
        self._hid_once = True
        if self._first_hide is not None:
            try:
                self._first_hide()
            except Exception:  # noqa: BLE001
                log.warning("Could not show the still-running notice", exc_info=True)

    def _watch_the_first_load(self):
        if self.loaded.wait(self._watchdog_seconds):
            with self._lock:
                wanted, self._show_when_ready = self._show_when_ready, False
            if wanted:
                self.show()
            return
        log.warning(
            "The app window did not load the page within %s seconds; opening the browser instead.",
            self._watchdog_seconds,
        )
        self.broken = True
        self._open_browser()

    def _call(self, function):
        try:
            function()
        except Exception:  # noqa: BLE001 - a window call must never take down the tray or AppKit
            log.warning("A window call failed", exc_info=True)


# ---------------------------------------------------------------------------------------------
# The pywebview layer.


def available():
    """The pywebview module, if this computer can show the app's window; else WindowUnavailable.
    Choosing the backend is what fails when WebView2 or .NET is missing, so it is done here, on
    the main thread before anything is shown (pywebview does it again in `start`, harmlessly)."""
    try:
        import webview

        guilib = importlib.import_module("webview.guilib").initialize()
    except Exception as exc:  # noqa: BLE001 - ImportError, WebViewException, a .NET load error
        raise WindowUnavailable(f"{type(exc).__name__}: {exc}") from exc
    renderer = getattr(guilib, "renderer", None)
    if renderer not in SUPPORTED_RENDERERS:
        raise WindowUnavailable(f"only the {renderer!r} web engine is available (WebView2 is missing)")
    return webview


def create(webview, url, shell):
    """Make the (hidden) window and wire its events to `shell`."""
    window = webview.create_window(
        TITLE,
        url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        hidden=True,
        background_color=BACKGROUND,
    )
    shell.attach(window)
    window.events.shown += shell.on_shown
    window.events.loaded += shell.on_loaded
    window.events.minimized += shell.on_minimized
    window.events.restored += shell.on_restored
    window.events.closing += shell.on_closing
    return window


def run(webview, shell, storage_path, debug=False, after_shown=None, icon=None):
    """Run the window's event loop on this (the main) thread until the window is closed for good.

    Page storage (the secret, the page's settings) survives restarts and updates. On Windows it is
    kept in `storage_path`, in the app's data folder. On macOS pywebview ignores `storage_path` and
    uses WebKit's own store for the app (outside the app bundle, per user), so the window's storage
    is not in the data folder there. Exports and backups go through the system's Save dialog, and
    links that open a new tab (papers, DOIs) open in the default browser.
    `after_shown()` runs once the window exists, on a worker thread. `icon` (a file) replaces the
    window's icon (Windows) or the Dock icon (macOS); without it they come from the executable or
    app bundle, which is right for the packaged app."""
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = bool(debug)

    def started():
        if not shell.shown.wait(60):
            return
        if sys.platform == "win32":
            _windows_setup(shell)
        if after_shown is not None:
            try:
                after_shown()
            except Exception:  # noqa: BLE001
                log.warning("Setting up after the window appeared failed", exc_info=True)

    options = {"private_mode": False, "storage_path": str(storage_path), "debug": bool(debug)}
    if icon:
        options["icon"] = str(icon)
    webview.start(started, **options)


def _windows_setup(shell):
    """The two things on Windows that need WinForms and WebView2 themselves (both public .NET
    API, reached through `window.native`, which pywebview documents as the native window):
    the close reason, and an editing-only right-click menu. Each is optional: without the first
    the close button still hides (pywebview's own event does it); without the second there is
    no right-click menu, and the keyboard still copies and pastes."""
    form = getattr(shell.window, "native", None)
    if form is None:
        return
    try:
        from System.Windows.Forms import CloseReason

        def form_closing(sender, args):
            try:
                keep = shell.on_native_closing(args.CloseReason == CloseReason.UserClosing)
                args.Cancel = bool(keep)
            except Exception:  # noqa: BLE001 - never leave the close stuck because of us
                log.exception("Deciding how the window closes failed")
                args.Cancel = False

        form.FormClosing += form_closing
        _KEEP_ALIVE.append(form_closing)
        shell.native_close = True
    except Exception:  # noqa: BLE001
        log.warning("Could not watch why the window closes; signing out may ask to close Lit Review", exc_info=True)

    def editing_menu():
        if not shell.loaded.wait(LOAD_WATCHDOG_SECONDS):
            return
        try:
            _invoke(form, lambda: _limit_context_menu(form))
        except Exception:  # noqa: BLE001
            log.warning("Could not set up the right-click menu", exc_info=True)

    threading.Thread(target=editing_menu, name="app-window-menu", daemon=True).start()


def _invoke(form, function):
    """Run `function` on the window's own thread (WinForms and WebView2 objects belong to it)."""
    from System import Action

    form.Invoke(Action(function))


def _limit_context_menu(form):
    from Microsoft.Web.WebView2.Core import CoreWebView2ContextMenuItemKind
    from Microsoft.Web.WebView2.WinForms import WebView2

    control = next((c for c in form.Controls if isinstance(c, WebView2)), None)
    core = control.CoreWebView2 if control is not None else None
    if core is None:
        log.warning("No WebView2 control in the window; the right-click menu stays off")
        return

    def requested(sender, args):
        items = args.MenuItems
        for index in range(items.Count - 1, -1, -1):
            item = items[index]
            if item.Kind != CoreWebView2ContextMenuItemKind.Separator and item.Name not in EDIT_MENU_ITEMS:
                items.RemoveAt(index)
        _tidy_separators(items, CoreWebView2ContextMenuItemKind.Separator)
        if items.Count == 0:
            args.Handled = True  # nothing to offer here (not in a text box or on a link): no menu

    core.ContextMenuRequested += requested
    core.Settings.AreDefaultContextMenusEnabled = True
    _KEEP_ALIVE.append(requested)


def _tidy_separators(items, separator):
    """No separator first, last, or next to another one."""
    index = 0
    while index < items.Count:
        is_separator = items[index].Kind == separator
        at_edge = index == 0 or index == items.Count - 1
        doubled = is_separator and index > 0 and items[index - 1].Kind == separator
        if is_separator and (at_edge or doubled):
            items.RemoveAt(index)
            index = max(0, index - 1)
        else:
            index += 1
