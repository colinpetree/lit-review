"""The macOS-only parts of the tray, kept apart so the logic can be tested anywhere.

What macOS needs that pystray does not give us:

* **A menu-bar picture that fits.** pystray squeezes whatever image it is given into a
  22 pixel square, which is blurry on a Retina screen and fills the whole bar. We
  replace it with a small "template" image (a plain black cap) shown at 18 points and
  drawn from 36 pixels; the system recolours a template for light and dark bars.
* **A Dock menu with "Open Lit Review".** The Dock's right-click menu is the system's
  own unless the app's delegate supplies items (`applicationDockMenu:`).
* **A click on the Dock icon, or a second double-click on the app, opens the browser.**
  Launch Services does not start a second copy of a running .app; it tells the running
  one to "reopen" (`applicationShouldHandleReopen:hasVisibleWindows:`).
* **Cmd+Q and the Dock's Quit go through our quit path.** Otherwise they end the process
  underneath `main()` (no "a job is running, quit anyway?" question, no clean-up), and
  without a main menu Cmd+Q may do nothing at all.

The behaviour (what to do on a reopen, on a quit request, in which thread) lives in
`MacActions`, plain Python with no AppKit, and is tested on any computer. `install` is
the thin AppKit layer around it; it needs a Mac to run, and wraps everything in
`try/except` so that if anything here fails the app still starts and works as before.
"""

import logging
import os
import threading
import time

log = logging.getLogger(__name__)

# macOS sends a "reopen" while launching an app on some versions, when the browser is
# already being opened, so one this soon after start is not a second double-click.
REOPEN_IGNORE_SECONDS = 4

# NSApplicationTerminateReply values.
TERMINATE_CANCEL = 0
TERMINATE_NOW = 1

MENU_ICON_POINTS = 18  # the size the menu-bar picture is shown at; the file is 2x that

ST_RDONLY = 1  # the POSIX "read-only filesystem" flag of statvfs (os.ST_RDONLY; Windows has neither)

RUN_FROM_INSTALLER_MESSAGE = (
    "Lit Review is running from the installer or a temporary location. "
    "Drag Lit Review into your Applications folder, then open it from there."
)


def running_from_read_only_volume(path):
    """True when `path` is on a read-only volume: the mounted disk image the app is
    installed from, the read-only copy macOS runs a freshly downloaded app from
    ("App Translocation"), or read-only media. From there the app cannot update itself
    and the disk cannot be ejected. An app in Applications, or any folder the user can
    write, is on a writable volume (whoever may write to it), so it is never flagged.
    Anything unreadable counts as "no", so the app then starts as before."""
    statvfs = getattr(os, "statvfs", None)
    if statvfs is None or not path:
        return False
    try:
        return bool(statvfs(os.path.realpath(path)).f_flag & ST_RDONLY)
    except (OSError, ValueError, AttributeError):
        return False


class MacActions:
    """What the delegate's callbacks do, with no AppKit in sight.

    open_app()      open the browser on the running app
    open_logs()     show the log folder
    confirm_quit()  True to go ahead and quit (asks first if a job is running)
    stop()          end the tray's event loop, so main() runs its normal clean-up
    """

    def __init__(self, open_app, open_logs, confirm_quit, stop, clock=time.monotonic, start_thread=None):
        self.open_app = open_app
        self.open_logs = open_logs
        self._confirm_quit = confirm_quit
        self._stop = stop
        self._clock = clock
        self._started = clock()
        self._asking = False
        self._lock = threading.Lock()
        self._start_thread = start_thread or self._thread

    @staticmethod
    def _thread(target):
        threading.Thread(target=target, name="quit-confirm", daemon=True).start()

    def reopen(self):
        """The Dock icon was clicked, or the app was opened a second time."""
        if self._clock() - self._started >= REOPEN_IGNORE_SECONDS:
            self.open_app()

    def terminate_requested(self, system_quit):
        """Cmd+Q, Dock Quit, or the system quitting every app (log out, restart, shut
        down). Returns the reply for `applicationShouldTerminate:`.

        A system quit is allowed at once: answering "cancel" makes macOS report that
        this app interrupted the log out. Our own writes are atomic (SQLite) and the
        OS drops the lock file, so being ended without clean-up is safe.

        A quit the user asked for is **always answered "cancel"**, so that AppKit does
        not end the process under `main()`. If the user agrees, `stop()` ends the event
        loop and `main()` shuts down normally. The question is asked on another thread,
        because the dialog waits on a subprocess and this is the thread that runs the
        menu bar and Dock."""
        if system_quit:
            return TERMINATE_NOW
        with self._lock:
            if self._asking:  # a question is already on screen
                return TERMINATE_CANCEL
            self._asking = True
        self._start_thread(self._ask_and_stop)
        return TERMINATE_CANCEL

    def _ask_and_stop(self):
        try:
            if self._confirm_quit():
                self._stop()
        except Exception:  # noqa: BLE001 - never leave "asking" set, or Quit could never ask again
            log.exception("Asking whether to quit failed")
        finally:
            with self._lock:
                self._asking = False


def _four_char_code(text):
    return int.from_bytes(text.encode("ascii"), "big")


# The Apple event attribute that says why the system is quitting an app (it is on the
# quit events sent for log out, restart and shut down, and not on a user's Cmd+Q).
QUIT_REASON_KEYWORD = "why?"

_delegate_class = None


def _is_system_quit(foundation):
    """True when the quit being handled was sent by the system (log out, restart, shut
    down) rather than asked for by the user. Any trouble reading it counts as the
    user's quit, which at worst asks a question."""
    try:
        event = foundation.NSAppleEventManager.sharedAppleEventManager().currentAppleEvent()
        if event is None:
            return False
        return event.attributeDescriptorForKeyword_(_four_char_code(QUIT_REASON_KEYWORD)) is not None
    except Exception:  # noqa: BLE001
        return False


def _get_delegate_class(foundation):
    """The Objective-C delegate class, defined once (the runtime refuses a class of the
    same name twice, so it cannot be made per call). It holds no logic: every method
    hands over to the `MacActions` stored on the instance."""
    global _delegate_class
    if _delegate_class is not None:
        return _delegate_class

    class LitReviewAppDelegate(foundation.NSObject):
        actions = None
        dock_menu = None

        def applicationDockMenu_(self, sender):
            return self.dock_menu

        def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, has_visible_windows):
            self.actions.reopen()
            return False  # there is no window of ours to bring forward

        def applicationShouldTerminate_(self, sender):
            return self.actions.terminate_requested(_is_system_quit(foundation))

        def openApp_(self, sender):
            self.actions.open_app()

        def openLogs_(self, sender):
            self.actions.open_logs()

    _delegate_class = LitReviewAppDelegate
    return _delegate_class


def _menu_item(appkit, title, action, key="", target=None):
    item = appkit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
    if target is not None:
        item.setTarget_(target)
    return item


def _build_dock_menu(appkit, delegate):
    menu = appkit.NSMenu.alloc().initWithTitle_("Lit Review")
    menu.addItem_(_menu_item(appkit, "Open Lit Review", b"openApp:", target=delegate))
    menu.addItem_(_menu_item(appkit, "Open log folder", b"openLogs:", target=delegate))
    return menu


def _build_main_menu(appkit, delegate):
    """A minimal main menu: with none, Cmd+Q has nothing to trigger. Quit sends the
    standard `terminate:` to the application, which lands in the delegate."""
    main_menu = appkit.NSMenu.alloc().init()
    holder = appkit.NSMenuItem.alloc().init()
    main_menu.addItem_(holder)
    app_menu = appkit.NSMenu.alloc().initWithTitle_("Lit Review")
    app_menu.addItem_(_menu_item(appkit, "Open Lit Review", b"openApp:", target=delegate))
    app_menu.addItem_(appkit.NSMenuItem.separatorItem())
    app_menu.addItem_(_menu_item(appkit, "Quit Lit Review", b"terminate:", key="q"))
    holder.setSubmenu_(app_menu)
    return main_menu


def install(actions):
    """Make the app behave like a Mac app: Dock menu, Dock-click reopen, quit routing and
    a main menu. Returns the delegate (the caller must keep it alive: AppKit holds its
    delegate weakly) or None if it could not be installed, in which case the caller
    falls back to the older reopen handler."""
    try:
        import AppKit
        import Foundation

        delegate = _get_delegate_class(Foundation).alloc().init()
        delegate.actions = actions
        delegate.dock_menu = _build_dock_menu(AppKit, delegate)
        app = AppKit.NSApplication.sharedApplication()
        app.setDelegate_(delegate)
        app.setMainMenu_(_build_main_menu(AppKit, delegate))
        return delegate
    except Exception:  # noqa: BLE001 - the app works without it, it just feels less like a Mac app
        log.warning("Could not set up the Mac app menu and Dock behaviour", exc_info=True)
        return None


def set_menu_bar_image(icon, image_path):
    """Replace pystray's menu-bar picture with the template image, at 18 points. Runs on
    the main thread (AppKit objects belong there; pystray's own setup callback runs on
    another). Called once, after the icon is visible; pystray only redraws its picture
    when the icon changes, which we never do, so ours stays. Uses pystray's private
    `_status_item`, so every step is guarded and a failure leaves the stock picture."""
    try:
        from PyObjCTools import AppHelper
    except Exception:  # noqa: BLE001
        log.warning("Could not place the menu-bar image (no AppHelper)", exc_info=True)
        return

    def apply():
        try:
            import AppKit
            import Foundation

            with open(image_path, "rb") as handle:
                raw = handle.read()
            data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
            image = AppKit.NSImage.alloc().initWithData_(data)
            image.setSize_(Foundation.NSMakeSize(MENU_ICON_POINTS, MENU_ICON_POINTS))
            image.setTemplate_(True)
            icon._status_item.button().setImage_(image)
            icon._lit_review_menu_image = image  # keep it alive with the icon
        except Exception:  # noqa: BLE001
            log.warning("Could not place the menu-bar image", exc_info=True)

    AppHelper.callAfter(apply)
