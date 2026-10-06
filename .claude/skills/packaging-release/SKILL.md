---
name: packaging-release
description: How Lit Review is packaged, released and auto-updated (PyInstaller build, tray and macOS app behaviour, updater and signed manifest, release workflow, user docs, license notices). Use when touching packaging/, pyinstaller.spec, updater.py, tray.py, mac_app.py, ui.py, logfile.py, selfcheck.py, the release workflow, RELEASING.md, INSTALL.md, or the license/notices pages.
---

# Packaging and release

The primary user gets a double-click app, not source. Build, from the repo root, on the OS you are
building for (PyInstaller cannot cross-compile; CI builds all three):
```
cd frontend; npm run build                  # writes backend/static
python packaging/make_icons.py              # packaging/build/: LitReview.ico, tray.png, trayTemplate.png, LitReview.iconset
python packaging/make_notices.py            # THIRD_PARTY_NOTICES.txt (licenses of what is bundled)
pyinstaller backend/pyinstaller.spec --noconfirm     # needs backend/requirements-build.txt
python packaging/smoke_test.py "dist/Lit Review/Lit Review.exe"   # self-check, then a real launch
```
`packaging/icon-source.png` is the one logo: 1024x1024, transparent, its own corners rounded about
160 px. The script makes the Windows `.ico` from it as it is and the macOS look itself: art scaled
to 824 px, squircle mask, drop shadow. `iconutil -c icns` runs only on a Mac, so CI does that step.
Use `--distpath`/`--workpath` to build outside the repo; `/build`, `/dist` and `packaging/build` are
gitignored.

- **What the packaged app is:** a PyInstaller onedir folder, `console=False`, with a tray (Windows) or
  menu-bar (macOS) icon and no console. `main()` in `app.py` serves on a thread and runs the tray
  (`tray.py`, pystray) on the main thread, since macOS needs its event loop there. From source the
  tray is off (console and Ctrl+C); `--tray` turns it on, `--no-tray` or `LIT_REVIEW_NO_TRAY=1`
  turns it off (tests, CI). Quit from the tray asks first if a slow job holds an `_exclusive` lock
  (`_jobs_running`), and the server thread dying takes the icon down with it. Shutdown and cleanup
  (`server_close`, `clear_instance`, lock release, log teardown) all happen in `main()`'s `finally`,
  never in the tray callback.
- **No console means no stdout/stderr** (they are `None`: a `print` is a silent no-op and a message
  is lost). `ui.py` is how anything is told to the user: `show_error` prints when there is a console
  and otherwise opens the OS's own dialog (a Windows message box; `osascript` on macOS with the text
  as arguments, never inside the script), `confirm` asks yes/no, `ensure_streams` replaces missing
  streams with devnull. No GUI toolkit (tkinter is excluded: it would fight pystray on macOS).
  `LIT_REVIEW_NO_DIALOG=1` turns dialogs off. The launch link carries the secret, so those two
  `print`s stay console-only and never go through anything that logs.
- **Log file:** `logfile.setup` (called in `main()` after the lock is won, so a hand-over launch writes
  nothing) keeps warnings and errors in `<data dir>/logs/lit-review.log` (1 MB x 3), every line
  passed through `source_http.redact` (it hides `key=`, `api_key=` and `token=` values). Request lines
  are not kept. Tray: "Open log folder".
- **Finding files:** `bundle.resource_path` (static files, `tray.png`, `trayTemplate.png`): `sys._MEIPASS` when frozen,
  the backend folder otherwise. Never use `__file__` for a shipped file. The data and key folders still
  come from platformdirs with app name `lit-review` (`credentials.APP_NAME`), so a packaged copy sees
  the same database and keys as a source run: do not change that name (a test pins it).
- **Version:** `version.py` says `0.0.0-dev`; the workflow rewrites it from the tag, so the tag is the
  one place a version is decided. `GET /api/about` returns the version and the data and log folders
  (Settings, "Software and Updates"). A dev version never updates.
- **`--self-check`** (`selfcheck.py`): imports every provider module (from `llm.PROVIDERS`), builds each
  SDK client with a dummy key, loads the certificate stores, checks `static/index.html`, and writes JSON
  to `LIT_REVIEW_SELFCHECK_FILE`, exit code 0/1 (a windowed exe has no stdout). It cannot see
  everything lazy, so the release checklist also makes one real call per provider and per source.
- **Updates** (`updater.py`, `update_manifest.py`, `app_settings.py`, `packaging/update_helper.py`).
  The packaged app **always** checks (no user switch: the AI models it uses get retired, so an old build must be
  able to learn of a fix): 30 s after start, then daily, on a background thread (`updater.start_background`, off
  from source and under `LIT_REVIEW_TESTING=1` + `LIT_REVIEW_NO_UPDATE_THREAD`, which the smoke test sets so CI
  never reaches GitHub). It fetches `update-manifest.json` and `.sig` straight from
  `github.com/.../releases/latest/download/` (not the rate-limited API), verifies the **Ed25519 signature over the raw
  bytes with a domain prefix** against `update_manifest.PUBLIC_KEYS` (two keys: active and spare), requires
  version == tag and strictly newer, then downloads the platform zip (HTTPS, GitHub hosts across redirects, **resumes**
  a partial file, signed size and SHA-256), unpacks it next to the install as `<install>.new` (zip-slip checks; `ditto`
  and `codesign --verify` on macOS) and runs the new build's `--self-check`, which must report the expected version.
  It never downloads while a search, lookup or grading run is active. Where the install cannot be replaced (read-only,
  translocated, not writable, long path) the state is `unsupported` with the manual link, quietly.
  **Applying:** the `auto_apply` setting (server-side `settings.json` in the config dir, default **off**) decides whether
  a staged update installs at the **next launch** (`apply_at_launch`, in `main()` after the instance lock and before the
  database is touched, so nothing is running) or waits for the page's **Install and restart** (`POST /api/update/apply`,
  which quiesces with `_GATE.close_when_quiet` like a restore, starts the helper and quits via `_QUIT["fn"]`). A running
  version below the manifest's signed `min_version` is "required": it installs at the next launch whatever the setting
  says. It is shown like any other update, just as quietly: the same **Update ready** dialog (also for someone with
  automatic installing on), worded "There is an update that is ready to install. This update will be applied automatically on the next start.", with no special banner and no "required" wording (it never locks anyone out of their data;
  only a failed install shows a banner, with the manual link). There is deliberately **no
  quit-time swap** (it races a relaunch, can be killed at logoff, and would raise the macOS App Management prompt while
  exiting). `state.json` in `<data>/updates/` counts attempts: a version that fails twice is marked `failed` and not
  retried. The helper (`packaging/update_helper.py`, stdlib only, built by the workflow into `update-helper[.exe]` and
  shipped inside the app) is copied out of the install folder and run with an argument list: wait for the old process,
  rename install to `.old`, new to install (retried), start the new copy with `--after-update` (it waits up to 30 s for
  the instance lock instead of handing over), wait for `started.json` naming the new version (written by `main()` once
  the server is up), then delete `.old`; otherwise roll back, restart the old one and write `result.json`, which the
  next launch turns into a message (`updater.take_result`, `note_failure`). The marker is written **before** cleanup
  runs, because cleanup deletes `.old`. A launch that applies a staged update has no page to say so and the old copy has already gone, so the helper (started with `--announce`) shows a small "Updating Lit Review" window until it is done, however it ends (Windows `MessageBoxW`, closed with `WM_CLOSE`; Mac an `osascript` dialog, terminated, with a 3 minute give-up). The Install update button does not ask for it: the page already says so. The database is backed up to `updates/before-update-<version>.db` first.
  Test-only overrides (`LIT_REVIEW_UPDATE_BASE` loopback URL, `LIT_REVIEW_UPDATE_PUBKEY`) work only with
  `LIT_REVIEW_TESTING=1`. Page: `UpdateProvider` (one shared poll of `GET /api/update-check`, a status read that also
  names this run of the app via `instance`), `UpdateModal` (the **Update ready** dialog: opens when a download
  finishes and at every start that finds one staged, only when `auto_apply` is off; Install update, or Not now / X /
  Escape / click away, remembered per run and version in sessionStorage), `UpdateBanner` (restarting, failed; a waiting update is deliberately not a banner), and Settings "New versions" (`UpdatesCard`: the
  toggle, **Check now**, and the same **Install update** button whenever one is staged, for auto users too).
  `lib/updateCheck.js` holds the pure logic (tested). Release side: CI writes the unsigned manifest
  (`make_manifest.py`, zips only, never the `.dmg`); the maintainer signs the draft (`sign_release.py`) and publishes; see
  `RELEASING.md`. Needs the repo to be **public**. Verified on real Windows and Intel Mac machines, manual and automatic, but not yet on Apple Silicon; what remains unproven is in RELEASING.md "Still to prove".
- **macOS specifics** (`mac_app.py`, wired in by `tray.Tray.run`; all of it is **untested off a Mac**, so a
  new build needs a look on a real one). The behaviour is in `MacActions` (plain Python, tested anywhere in
  `tests/test_mac_app.py`); `install()` is the thin AppKit layer, wrapped in `try/except` so a failure leaves
  the app working as before (and falls back to the older `tray.register_reopen` Apple-event handler).
  The app is a normal Dock app (`LSUIElement` off). An app delegate gives it: a **Dock menu** ("Open Lit
  Review", "Open log folder"), **reopen** (a click on the Dock icon, or opening the app a second time, opens
  the browser: Launch Services never starts a second process of a running .app, so the Windows hand-over
  does not apply; ignored for 4 s after launch), a minimal **main menu** so Cmd+Q has something to trigger,
  and **quit routing**: Cmd+Q and the Dock's Quit land in `applicationShouldTerminate:`, which always answers
  "cancel" (so AppKit never ends the process under `main()`) and asks `_confirm_quit` on a worker thread
  (the dialog waits on `osascript`, and the main thread runs the menu bar); if the user agrees `Tray.stop()`
  ends the loop and `main()` cleans up normally. A quit **sent by the system** (log out, restart, shut down,
  recognised by the Apple event's `'why?'` attribute) is answered "terminate now", because cancelling it
  makes macOS say the app interrupted the log out. The menu-bar picture is `trayTemplate.png` (made by
  `packaging/make_icons.py:menu_template`: a plain black cap on transparent, 36 px shown at 18 points, as a
  "template" image the system recolours for light, dark and Liquid Glass bars; the cap's width is
  `MENU_GLYPH_WIDTH_PX`, a first guess to tune on a Mac). pystray would otherwise squeeze the full-colour logo
  into a 22 px square, so `mac_app.set_menu_bar_image` swaps it once the icon is visible (on the main thread,
  through pystray's private `_status_item`). **Liquid Glass app icon (macOS 26):** the classic `.icns` stays for
  macOS 11 to 15; a layered icon authored in Apple's Icon Composer as `packaging/macos/AppIcon.icon` (the cap
  as a foreground layer: `packaging/make_glyph_svg.py` writes the committed `packaging/macos/glyph-*.svg`, **filled outlines, not strokes**, because Icon Composer's per-layer Fill colours a layer's shapes and flooded a stroke-only cap)
  is compiled by the workflow's `icon` job (`xcrun actool`, Xcode 26 on `macos-latest`) into `Assets.car`,
  which the Mac builds copy into `Contents/Resources` **before signing** and name with `CFBundleIconName`
  (`pyinstaller.spec` sets it only when the compiled file exists, so a local build without it keeps the classic icon; the release workflow requires it and fails if the `.icon` is missing or does not compile).
  Bundle id `io.github.colinpetree.lit-review` (changing it makes macOS treat a release as a new app).
  Builds are signed ad hoc only; the first-launch "Open Anyway" step is in INSTALL.md.
- **Workflow** (`.github/workflows/release.yml`): `prepare` checks the tag is `vN.N.N` and on `main`;
  `build` (Windows, macOS arm64, `macos-15-intel`) installs the pinned requirements first, runs the frontend
  and backend tests, builds, ad-hoc signs the Mac app, runs `smoke_test.py` on the built app, and zips
  (`ditto` on Mac: `upload-artifact` would break an `.app`). Each Mac leg then makes a **disk image**
  (`hdiutil create` from a `dmg/` folder holding the same signed app and an `Applications` link; the step
  mounts it read-only, requires exactly those two items, runs `codesign --verify` and `--self-check` on the
  mounted app, proves the start-up check below on the runner (`/Applications` must read writable, the image
  read-only, and the app launched from the image must exit 1 and leave no `instance.lock`), and always
  detaches). The `.dmg` is what people download; the `.zip` stays for the updater
  (Plan 3), whose signed manifest must list the zips only. `release` (tag pushes only, the only job with
  write permission) first requires exactly 3 zips and 2 disk images, then makes a **draft** release with
  `SHA256SUMS.txt` for the maintainer to test and publish.
  **Read-only start-up check:** a packaged Mac app that finds its own volume read-only (the mounted disk
  image, a Gatekeeper-translocated copy, read-only media; `mac_app.running_from_read_only_volume`, via
  `statvfs`) shows `RUN_FROM_INSTALLER_MESSAGE` and exits 1 in `main()`, after the `--self-check` branch and
  before the instance lock, so everyone installs by dragging the app onto Applications. Any `statvfs` error
  means "not read-only" (the app starts as before).
  Actions are pinned by commit SHA. `workflow_dispatch` builds without releasing. The Intel runner label
  and the Mac legs skipping `test_app_instances.py` are the first things to check if CI misbehaves.
- **Docs for users:** `README.md`, `INSTALL.md` (plain language: no terminal, first-launch steps per OS,
  where data lives), `packaging/release-notes.md` (the release body). License: FSL-1.1-MIT (source-available: free for any use except a competing commercial product, each version turns MIT after 2 years; the author's choice, so do not swap it for a permissive license without asking); the bundled software's
  licenses ship as `THIRD_PARTY_NOTICES.txt` (made by `packaging/make_notices.py`: Python packages, npm
  packages, and the Python runtime with its native libraries), which with `LICENSE` is **inside the app** in a
  `licenses` folder (data files in `pyinstaller.spec`, added before the Mac signature; the spec stops if the notices
  were not made), so the zips hold only the app. The zip step lists where the files landed. Settings, "License and
  Notices" is a page with two cards. `LicenseCard` (`LicenseModal`): the modal shows the repo's `LICENSE` embedded at
  build time (`?raw` import, so `vite.config.js` lets the dev server read the repo root), and the card lists what
  is sent to AI companies and databases. `ThirdPartyCard` (`ThirdPartyNoticesModal`): reads the packaged notices from
  `GET /api/notices` (`notices.py`: two fixed paths, 2 MB cap, never a path from the request; 404 with a plain
  message in a source run until `make_notices.py` has been run), fetched once and kept (`lib/notices.js`); both
  modals share `TextModal`. The self-check and the smoke test fail a packaged build without them. If a new
  feature sends data somewhere new, update those notices.
