# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the packaged Lit Review (a folder per OS: Lit Review.exe
on Windows, Lit Review.app on macOS). Build from the repo root, after
`npm run build` in frontend/ (it writes backend/static) and
`python packaging/make_icons.py` (it writes packaging/build/):

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
if (ICON_DIR / "tray.png").is_file():
    datas += [(str(ICON_DIR / "tray.png"), ".")]

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

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(exe_icon) if exe_icon and exe_icon.is_file() else None,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # A normal app with a Dock icon (Cmd+Q and the Dock menu quit it). Menu-bar only
            # would be "LSUIElement": True, but then there is no Dock icon to click.
        },
    )
