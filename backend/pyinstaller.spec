# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the packaged Lit Review (a folder per OS: Lit Review.exe
on Windows, Lit Review.app on macOS). Build from the repo root, after
`npm run build` in frontend/ (it writes backend/static) and
`python packaging/make_icons.py`, `python packaging/make_notices.py` and
`pyinstaller packaging/update_helper.py --onefile --name update-helper --distpath packaging/build`
(each writes into packaging/build/):

    pyinstaller backend/pyinstaller.spec --noconfirm

PyInstaller cannot cross-compile, so each OS builds its own (see
.github/workflows/release.yml). A clean build proves little: what goes wrong is a
module that is only imported when a feature runs, so always run the result, and
`"Lit Review" --self-check` (selfcheck.py) lists what is missing.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH)  # backend/
ROOT = SPEC_DIR.parent
ICON_DIR = Path(os.environ.get("LIT_REVIEW_ICON_DIR") or ROOT / "packaging" / "build")

sys.path.insert(0, str(SPEC_DIR))
import llm  # noqa: E402 - the table of AI providers, which are loaded by name at run time
from version import __version__  # noqa: E402

APP_NAME = "Lit Review"
BUNDLE_ID = "io.github.colinpetree.lit-review"  # keep it the same in every release

# Packages that load parts of themselves at run time, which static analysis misses.
COLLECT_ALL = [
    "anthropic",
    "openai",
    "google.genai",
    "pydantic",
    "pydantic_core",
    "anyio",
    "httpx",
    "httpcore",
    "cryptography",
    "certifi",
    "pystray",
]
datas, binaries, hiddenimports = [], [], []
for package in COLLECT_ALL:
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

# The AI provider modules are imported by name (llm.PROVIDERS), so nothing in the
# code imports them. Taken from that table, so a new provider is never forgotten.
hiddenimports += sorted(set(llm.PROVIDERS.values()))
hiddenimports += collect_submodules("providers")
hiddenimports += ["pystray._win32"] if sys.platform == "win32" else []
hiddenimports += ["pystray._darwin"] if sys.platform == "darwin" else []

datas += collect_data_files("certifi")  # HTTPS fails once frozen without the certificate bundle
datas += [(str(SPEC_DIR / "static"), "static")]  # the built frontend
for tray_image in ("tray.png", "trayTemplate.png"):  # Windows tray icon, macOS menu-bar icon
    if (ICON_DIR / tray_image).is_file():
        datas += [(str(ICON_DIR / tray_image), ".")]

# The app's license and the third-party notices travel inside the app, in a `licenses` folder
# (Settings, License and Notices reads the notices from there; see notices.py), rather than
# loose beside it in the zip. They are added here, before the Mac app is signed, so the
# signature covers them. The notices are made by packaging/make_notices.py, which the
# workflow runs before this build; a build without them would ship without the notices that
# the software it carries asks for, so it stops instead.
NOTICES = ROOT / "packaging" / "build" / "THIRD_PARTY_NOTICES.txt"
if not NOTICES.is_file():
    raise SystemExit(f"{NOTICES} is missing: run `python packaging/make_notices.py` before building")
datas += [(str(ROOT / "LICENSE"), "licenses"), (str(NOTICES), "licenses")]

# The update helper (packaging/update_helper.py, built on its own as a small standalone program by
# the workflow) swaps a downloaded update in while the app is not running. It ships as a data file;
# the app copies it out of the install folder before running it, since it renames that folder. An
# app without it could not update itself, so a build without it stops.
HELPER = ROOT / "packaging" / "build" / ("update-helper.exe" if sys.platform == "win32" else "update-helper")
if not HELPER.is_file():
    raise SystemExit(f"{HELPER} is missing: build packaging/update_helper.py with PyInstaller before this build")
datas += [(str(HELPER), ".")]

if sys.platform == "win32":
    exe_icon = ICON_DIR / "LitReview.ico"
elif sys.platform == "darwin":
    exe_icon = ICON_DIR / "LitReview.icns"
else:
    exe_icon = None

a = Analysis(
    [str(SPEC_DIR / "app.py")],
    pathex=[str(SPEC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # tkinter is not used (dialogs are the operating system's own); tests are not shipped.
    excludes=["tkinter", "_tkinter", "pytest", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: files stay beside the executable
    name=APP_NAME,
    console=False,  # no console window: the tray icon is the app's visible part
    icon=str(exe_icon) if exe_icon and exe_icon.is_file() else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=APP_NAME)

# macOS 26 draws an app icon in "Liquid Glass" from a layered icon compiled into Assets.car
# (CI makes it from packaging/macos/AppIcon.icon and puts it in ICON_DIR). The key below
# tells the system to look for it; the .icns stays for macOS 11 to 15. Without the compiled
# file the key is left out, so a build without it behaves exactly as before. The workflow
# also copies Assets.car into Contents/Resources after this build and before signing.
ASSETS_CAR = ICON_DIR / "Assets.car"

if sys.platform == "darwin":
    mac_info_plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": __version__,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # A normal app with a Dock icon (Cmd+Q and the Dock menu quit it). Menu-bar only
        # would be "LSUIElement": True, but then there is no Dock icon to click.
    }
    if ASSETS_CAR.is_file():
        mac_info_plist["CFBundleIconName"] = "AppIcon"
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(exe_icon) if exe_icon and exe_icon.is_file() else None,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist=mac_info_plist,
    )
