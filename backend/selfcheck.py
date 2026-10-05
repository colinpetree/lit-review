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
    import certifi
    import httpx
    import requests

    for path in (certifi.where(), requests.utils.DEFAULT_CA_BUNDLE_PATH):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"certificate bundle missing: {path}")
    httpx.Client().close()  # loads the certificate store


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
