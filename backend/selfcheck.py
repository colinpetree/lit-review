"""`Lit Review --self-check`: does this build have everything it loads at run time?

A packaged app that built cleanly can still be missing a module that is only
imported when a feature runs (the AI SDKs load pieces lazily, and certificates are
a data file, not code), and that shows up on the user's computer as a broken
button. CI runs this on every packaged build to find that first.

The packaged app has no console, so the result is a JSON file named by
`LIT_REVIEW_SELFCHECK_FILE` (when set) as well as the exit code: 0 all good, 1 not.
No network is used and no keys are read.
"""

import importlib
import json
import os
import sqlite3
import sys

import bundle
import llm
import updater
import version


def _check_provider_modules():
    # Every provider the app can use, taken from the app's own table, so a new one
    # is checked without anyone remembering to list it.
    for module in sorted(set(llm.PROVIDERS.values())):
        importlib.import_module(module)
    importlib.import_module("providers.openai_compat")


def _check_sdk_clients():
    """Build each SDK's client with a dummy key and touch the part of it the app
    calls, which pulls in the SDK's lazily loaded pieces (and the TLS setup)."""
    import anthropic
    import openai
    from google import genai
    from google.genai import errors, types  # noqa: F401 - imported by providers.gemini

    anthropic.Anthropic(api_key="self-check").messages
    openai.OpenAI(api_key="self-check").chat.completions
    genai.Client(api_key="self-check").models


def _check_certificates():
    """Both ways the app checks certificates work in this build. `requests` (the paper sources,
    the updater) uses certifi's bundled file. The AI SDKs send through httpx2, which on Windows
    and macOS asks the operating system's own certificate store through `truststore` (it loads
    the system's libraries by ctypes, so a build can lack a piece without failing to start).

    This checks the build, never this computer's settings: httpx2 uses a file named by
    SSL_CERT_FILE or SSL_CERT_DIR instead of the system store when one is set, which is a choice
    the user made and works. The updater runs this on the user's computer and refuses an update
    that fails it, so a check of which context httpx2 picks here would block updates for them."""
    import ssl

    import certifi
    import httpx2
    import requests

    for path in (certifi.where(), requests.utils.DEFAULT_CA_BUNDLE_PATH):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"certificate bundle missing: {path}")
    if sys.platform in ("win32", "darwin"):
        import truststore

        truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    httpx2.Client().close()


def _check_storage():
    from cryptography.fernet import Fernet

    token = Fernet(Fernet.generate_key())
    assert token.decrypt(token.encrypt(b"x")) == b"x"
    sqlite3.connect(":memory:").execute("select 1").fetchone()
    for name in ("filelock", "platformdirs"):
        importlib.import_module(name)


def _check_tray():
    # pystray picks its backend when imported, so this catches a missing one.
    # Showing an icon needs a display, which a CI machine may not have.
    import PIL.Image  # noqa: F401
    import pystray  # noqa: F401

    if sys.platform == "darwin":
        # What mac_app.py needs at run time (pystray itself already imports the first two).
        import AppKit  # noqa: F401
        import Foundation  # noqa: F401
        from PyObjCTools import AppHelper  # noqa: F401


# What the app window needs on Windows, as files inside the build (pywebview's WebView2 SDK and
# loader, and pythonnet's .NET bridge), relative to each package's own folder.
WINDOW_FILES_WINDOWS = [
    ("webview", "lib", "Microsoft.Web.WebView2.Core.dll"),
    ("webview", "lib", "Microsoft.Web.WebView2.WinForms.dll"),
    ("webview", "lib", "runtimes", "win-x64", "native", "WebView2Loader.dll"),
    ("pythonnet", "runtime", "Python.Runtime.dll"),
    ("clr_loader", "ffi", "dlls", "amd64", "ClrLoader.dll"),
]
WINDOW_MODULES = {
    "win32": ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "clr_loader"],
    "darwin": ["webview.platforms.cocoa", "WebKit", "Quartz"],
}


def _check_window():
    """The app window's library, its backend for this OS and the files they load are in the build.

    This only looks for them; it loads nothing that depends on the computer. The updater runs a new
    version's self-check on the user's own computer and refuses the update if it fails, while the
    app itself falls back to the browser where the window cannot be used (no WebView2, a damaged
    .NET, an old Windows). So a check that loaded .NET, or AppKit's application object, could stop
    a computer from ever updating although the app works on it. What it catches is a build that
    lost a hidden import or a data file, which would fall back to the browser on every computer."""
    import importlib.util
    from pathlib import Path

    import webview  # pure Python until a backend is chosen

    missing = [name for name in WINDOW_MODULES.get(sys.platform, []) if importlib.util.find_spec(name) is None]
    if missing:
        raise ModuleNotFoundError(f"missing from the build: {', '.join(missing)}")
    if sys.platform == "win32":
        folders = {"webview": Path(webview.__file__).parent}
        for package in ("pythonnet", "clr_loader"):
            folders[package] = Path(importlib.util.find_spec(package).origin).parent
        for package, *parts in WINDOW_FILES_WINDOWS:
            path = folders[package].joinpath(*parts)
            if not path.is_file():
                raise FileNotFoundError(f"missing {path}")


def _check_files():
    required = [("static", "index.html")]
    if bundle.is_frozen():
        # Without them the tray falls back to a stand-in or, on a Mac, to the large stock
        # icon, which is easy to miss and looks wrong, so a packaged build must have them.
        required += [("tray.png",), ("trayTemplate.png",)]
        # The license and notices travel inside the app (Settings shows them), so a
        # packaged build without them would ship without what its libraries ask for.
        required += [("licenses", "LICENSE"), ("licenses", "THIRD_PARTY_NOTICES.txt")]
        # Without the helper the app could never install an update.
        required += [(updater.HELPER_NAME,)]
    for parts in required:
        path = bundle.resource_path(*parts)
        if not path.is_file():
            raise FileNotFoundError(f"missing {path}")


def _check_update_signing():
    """The updater trusts a download only if an Ed25519 signature verifies, so a build whose
    cryptography cannot do that would offer updates it can never accept."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import update_manifest

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signature = base64.b64encode(private.sign(update_manifest.SIGNATURE_PREFIX + b"x"))
    assert update_manifest.verify_signature(b"x", signature, [base64.b64encode(public).decode()])
    assert not update_manifest.verify_signature(b"y", signature, [base64.b64encode(public).decode()])


def _check_update_helper():
    """The packaged update helper starts and answers, so an update is not found to be
    impossible only when a user tries one."""
    if not bundle.is_frozen():
        return
    import subprocess

    done = subprocess.run([str(bundle.resource_path(updater.HELPER_NAME)), "--help"], capture_output=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"the update helper exited {done.returncode}")


CHECKS = {
    "providers": _check_provider_modules,
    "sdk clients": _check_sdk_clients,
    "certificates": _check_certificates,
    "storage": _check_storage,
    "tray": _check_tray,
    "app window": _check_window,
    "files": _check_files,
    "update signing": _check_update_signing,
    "update helper": _check_update_helper,
}


def run():
    results = {}
    for name, check in CHECKS.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - report every failure, not just the first
            results[name] = f"FAILED: {type(exc).__name__}: {exc}"
    ok = all(value == "ok" for value in results.values())
    report = {"ok": ok, "version": version.__version__, "frozen": bundle.is_frozen(), "checks": results}
    path = os.environ.get("LIT_REVIEW_SELFCHECK_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    if sys.stdout is not None:
        print(json.dumps(report, indent=2))
    return 0 if ok else 1
