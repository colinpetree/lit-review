# Releasing Lit Review

Releases are built, tested, signed and published by GitHub Actions. There is no version number to type and no tag to push: you pick patch, minor or major and click Approve.

- **Every pull request and every merge to `main`** runs CI (`.github/workflows/ci.yml`, building with `build-test.yml`).
- **Every merge to `main` that passes** is built as the **next patch version** and left as a draft release, the **Candidate**, holding the exact files that were tested.
- **To release:** Actions, **Publish release** (`.github/workflows/release.yml`), pick patch, minor or major, then **Approve**. GitHub signs the update manifest with the active key (kept in the `release` environment) and publishes.
- **Versions** are counted on from the highest `vX.Y.Z` any release or tag has used, so a number is never used twice (see "Pulling a bad release"); builds are tested against the newest published release. `backend/version.py` always says `0.0.0-dev` in the repository; the workflows write the version in when they build. Never push a `v*` tag by hand: nothing reacts to it, it cannot be deleted afterwards, and it only makes the numbering skip past it.

## What you do by hand (once)

1. **Settings, Advanced Security:** turn on Dependency graph, Dependabot alerts and Dependabot security updates.
2. **Settings, Environments, New environment `release`:**
   - Required reviewers: you. Leave **Prevent self-review off** (you start the run and approve it; with it on, nobody could).
   - Deployment branches: `main` only. Turn off **Allow administrators to bypass**.
   - Environment secrets: `UPDATE_SIGNING_KEY` (the whole text of the **active** `.pem` file) and `UPDATE_SIGNING_PASSPHRASE`. Only the Publish release `sign` job can read them, and never on a pull request.
3. **Settings, Rules, Rulesets** (both are set up):
   - **Protect main** (the default branch, no bypass): blocks deletion and force pushes, requires a pull request (no approvals needed) and these checks: `lint`, `backend-tests (windows-latest)`, `backend-tests (macos-latest)`, `frontend-tests`, `e2e`, `dependency-review`, `build / Build (Windows)`, `build / Build (macOS-Apple-Silicon)`, `build / Build (macOS-Intel)`, `build / collect` and the three CodeQL `analyze (...)`. "Require branches to be up to date" is off (the build on `main` tests the merged result anyway). A renamed CI job must be renamed here too, or no pull request can merge. Never skip CI for some files with `paths-ignore` on the trigger: the required checks would then never report.
   - **Protect version tags** (`refs/tags/v*`, excluding `refs/tags/v*-test.*`): release tags cannot be deleted or moved; Publish release can still create them, and test-build tags can be cleaned up.
4. Keep the **spare** key offline, away from GitHub (see "Signing keys" below).

Since every change reaches `main` through a pull request, start each branch from an up-to-date `main` (`git switch main`, `git pull`, `git switch -c <name>`): pull requests are squash-merged, so a branch made from an older branch's commits conflicts with `main`.

The signing keys were made once with `packaging/make_update_key.py`, and their public halves are in `backend/update_manifest.py` (`PUBLIC_KEYS`). Every installed copy trusts those two keys.

## Every merge: CI

Each pull request and each merge to `main` runs CI. It takes about **15 to 20 minutes**, and the slowest job sets the pace: the Windows backend tests with coverage (16 to 18 minutes; 45 allowed). Measured in November 2026, the others take:

| Job | Time |
|---|---|
| lint, frontend-tests, dependency-review, prepare | under a minute each |
| e2e | about 2 minutes |
| backend-tests on macOS | about 4 to 5 minutes |
| build: Windows / Apple Silicon / Intel Mac | about 4 / 4 to 6 / 8 to 9 minutes (each includes its smoke, browser, upgrade and, on `main`, rehearsal checks) |
| CodeQL (its own workflow) | about a minute |

What each job does:

- **lint**: ruff (`ruff.toml`), oxlint, actionlint (which also shellchecks every workflow step).
- **backend-tests**: pytest on Windows (with a coverage floor) and macOS. `tests/conftest.py` refuses the network, so no test reaches a real service or spends money. `test_route_inventory.py` checks every `/api` route against the access secret, the Host and Origin guards and junk bodies; `test_api_contract.py` checks the page and the server agree on every route.
- **frontend-tests**: Vitest (library and component tests), then a production build.
- **e2e** (Windows): the background-job flow in a real browser (`frontend/scripts/verify-jobs.mjs`), from source, with the AI and the paper sources faked: a dataset is searched, an evaluation is estimated, confirmed, graded, stopped, resumed and exported.
- **build** (`build-test.yml`), on Windows, Apple Silicon and Intel Macs:
  - `packaging/smoke_test.py`: the app's own `--self-check`, a real launch, the hand-over to a running copy;
  - (Mac) the disk image, mounted read-only and checked;
  - (Windows) `packaging/browser_test.py`: a walk through the real pages in Chromium on sample data (`backend/ci_fixture.py`, `frontend/scripts/verify-app.mjs`), in light and dark;
  - `packaging/upgrade_test.py`: the previous release makes a database, this build migrates it and shows its data;
  - on `main` only, `packaging/update_rehearsal.py`: the previous release really updates itself to this build through the in-app updater (with a throwaway signing key and a server on the runner, so nothing reaches GitHub).
- **dependency-review** (pull requests only): fails on a newly added package with a known serious vulnerability.

Then:

- **Pull request:** tests only. Its builds are labelled `<newest release>-ci.<sha>`, which the updater and the usage counter both ignore.
- **Merge to `main`, everything passed:** a draft release **"Candidate 0.1.4 (abc1234), tested against v0.1.3"** with the five downloads, `SHA256SUMS.txt`, the exact Python packages in each build, and in its notes the commits and dependency changes since the last release. Each passing merge replaces it, so several merges (a batch of Dependabot updates, for example) ship together as one version. You can download and try it: drafts are private, and the app never sees them. (A Candidate you install reports itself as that version.)
- **Failed:** GitHub emails you, and the previous Candidate (if any) stays.

## Every release: Publish release

1. Check the newest CI run on `main` passed (a `Candidate` draft exists for it).
2. GitHub, **Actions**, **Publish release**, **Run workflow**. Leave "Use workflow from" on `main` and pick:
   - **patch** (usual): ships the Candidate's tested files as they are. Nothing is built: the draft is ready in under a minute, and signing and publishing after your Approve take about another.
   - **minor** or **major**: the version is compiled into the app, so this rebuilds the Candidate's commit with the new version and runs the build checks again, including the update rehearsal (about 10 to 15 minutes before the Approve prompt). It needs the Candidate to be the newest commit on `main` when you start it; if a merge is still in CI, wait for it.

   From a terminal: `gh workflow run release.yml -f bump=patch`.
3. The run leaves a draft **Lit Review X.Y.Z** with the downloads and the (unsigned) update manifest, and waits. GitHub emails you. Try the downloads from the draft if you like.
4. On the run's page: **Review deployments**, tick `release`, **Approve and deploy**. The `sign` job checks every zip against the manifest and against the build's `SHA256SUMS.txt`, signs the manifest, checks the signature against the keys built into the app, publishes the release (which makes the tag `vX.Y.Z` on the tested commit) and checks it the way the app will. It then removes old test pre-releases.

Installed copies find the release on their next daily check. The run summary lists any commits on `main` that came after the tested build and are therefore **not** in the release.

### If it stops

- **"No tested build waiting":** merge to `main` and wait for CI to pass.
- **"... is still waiting to be approved and signed":** an earlier release draft was never approved. Approve it (on its Publish release run, **Re-run failed jobs**, then Approve), or delete that draft on the Releases page.
- **You rejected Approve, or never gave it** (GitHub gives up after 30 days): the draft stays unpublished and untagged. To publish it later, open that run, **Re-run failed jobs**, then Approve. To give up, delete the draft: the version number is free again and the next merge makes a new Candidate.
- **A minor/major rebuild failed:** the draft is handed back as a Candidate. Fix the cause, merge, and publish again.
- **Anything else partway** (a GitHub error): run it again with the same bump; it carries on from the draft it claimed ("Publishing ..."). To give up on that instead, delete the "Publishing" draft.
- **"wait for CI on main to finish":** a minor/major release was started while a newer merge was still in CI. Wait for it to pass, then publish.
- **The sign job says the release is PUBLISHED but does not verify:** until fixed the app offers it to nobody. Delete the release on GitHub, or sign it again by hand (below), then check with `python packaging/sign_release.py --verify vX.Y.Z`.

### Pulling a bad release

Delete the release on GitHub (Releases, the release, Delete). What each copy then does:

- **Not downloaded it yet:** it is never offered. The app only looks at the latest published release, which is now the one before (copies older than that one are offered that one, as usual).
- **Downloaded it but not installed** (an "Update ready" waiting, or an automatic install due at the next start): the copy is withdrawn. Every check, and every install just before it starts, looks at the newest signed release; when that names a lower version than the downloaded copy, the copy's release must have been pulled (version numbers are never reused), so it is deleted instead of installed (`updater.withdraw_if_pulled`, logged as "was withdrawn after it was downloaded"). Only a correctly signed manifest can withdraw anything. A computer that is offline at that moment cannot know, and installs it as before.
- **Already installed it:** it keeps running the bad version until the fix arrives.

Its tag stays, on purpose: the **Protect version tags** ruleset stops version tags being deleted or moved, and that version number is used up for good (people may be running it). Numbering takes care of this by itself: versions are counted from the highest version any release **or tag** has used (`.github/scripts/version-base.sh`), while builds are still tested against the newest published release (`previous-release.sh`). So after pulling 0.1.5, the next merge to `main` builds as **0.1.6**, tested against v0.1.4, and a normal **patch** Publish ships the fix, which copies on the bad 0.1.5 are offered like everyone else. If the bad version cannot update itself, see "A release that old versions can no longer survive" below.

## Checking a branch

- **Tests only:** open a pull request, or Actions, **CI**, Run workflow, your branch, `mode: trial` (`gh workflow run ci.yml --ref <branch> -f mode=trial`). Nothing is published.
- **Downloads to try on a real computer:** the same with `mode: test`. After every check passes it publishes a **pre-release** `v<newest>-test.<branch>.<sha>` with the downloads. The in-app updater never offers a pre-release, and the next real release removes it.

## Dependencies

- **Dependabot** (`.github/dependabot.yml`) opens monthly pull requests for outdated Python and npm packages and GitHub Actions, grouped, and only for versions that have been out at least 7 days. Each runs the full CI. **AI SDK updates** (the `ai-sdks` group): CI cannot make a real AI call, so make one real scoring call with your own key before releasing one. `cryptography` is updated by hand (`requirements.txt` pins it twice on purpose, for Intel Macs).
- **Dependency audit** (`.github/workflows/dependency-audit.yml`) runs on the 1st of each month (or Run workflow): the packages in the latest release and what the next release would ship. If it finds a known vulnerability, the run fails and GitHub emails you. Dependabot alerts cover the time between.
- **Each release's notes** list the Python and npm packages that changed since the previous release. `requirements.txt` pins the packages it lists but not the packages they pull in, so read the list.
- **CodeQL** (`.github/workflows/codeql.yml`) scans the Python, the JavaScript and the workflow files on every pull request and weekly.

## Signing keys

- The **active** key's private half is in the `release` environment (above). Anyone who can approve a Publish release run in this repository (in practice, someone holding your GitHub session or your `gh` token) could ship a signed update, so keep the computer you use GitHub on clean and treat the `gh` token like a password.
- The **spare** key stays offline, never in GitHub. If the active key leaks: sign a release by hand with the spare (below) whose `PUBLIC_KEYS` drop the leaked key and add a new one, then put the new key in the environment.
- To make a new pair (outside the repository): `python packaging/make_update_key.py --active D:\keys\lit-review-active.pem --spare E:\keys\lit-review-spare.pem`. It asks for a passphrase for each and prints the `PUBLIC_KEYS` block for `backend/update_manifest.py`.

### Signing by hand (fallback)

If GitHub Actions cannot sign, or to sign with the spare key, with the GitHub CLI signed in:

```
python packaging/sign_release.py vX.Y.Z --key D:\keys\lit-review-active.pem --publish
python packaging/sign_release.py --verify vX.Y.Z
```

It does what the `sign` job does: re-hashes the zips, asks for the passphrase, signs, checks, uploads the signature, publishes and verifies.

## Usage counts

Packaged copies send anonymous counts (`backend/telemetry.py`) to the Worker in `telemetry-worker/` (setup, queries and what the numbers mean are in its README). `ENDPOINT` in `telemetry.py` is `https://litreview-data.colinpetree.com/`, so **deploy the Worker before the first release that has it** (until then copies just fail to send, quietly). The address is built into every shipped copy, so keep that hostname working for good (or answer 410 to make old copies stop). Do not add a version, ID or anything per person to the payload without updating the notices card, INSTALL.md and the Worker's validation. Builds that are not releases (`0.0.0-dev` from source, `-ci.` and `-test.` builds) never send.

## A release that old versions can no longer survive

If a retired AI model, or something like it, means old versions stop working, make the release a required one: run Publish release with **required_update** ticked and a short **notice** saying why ("The AI model Lit Review used was retired."). From a terminal: `gh workflow run release.yml -f bump=patch -f required_update=true -f notice="..."`. The floor (`min_version` in the signed manifest) is then the version being published, so every older copy must take it. (By hand, which can also set an older floor: `sign_release.py ... --min-version 0.1.2 --notice "..."`.)

Every copy older than the floor then treats the update as required: it downloads in the background, installs at the next start whatever the "install automatically" setting says, and shows the ordinary Update ready window when it finishes ("There is an update that is ready to install. This update will be applied automatically on the next start."). Nothing in the app calls it required, and it never blocks the app, so people can still reach their data. **Rehearse the update path first** (CI's update rehearsal does this from the previous release; try older ones by hand): a floor raised on a release whose install fails leaves everyone on the old version, with a banner explaining that the update could not be installed and a link to download it.

## What the updater needs from a release

- The three platform zips, named `Lit-Review-<version>-Windows.zip`, `-macOS-Apple-Silicon.zip`, `-macOS-Intel.zip`. The `.dmg` files are for people and are never listed in the manifest.
- A **public** repository, a **published** (not draft) release, and a signature that verifies. Anything else, and the app silently offers nothing.
- If a release changes the install layout (a different folder structure inside the zip), the updater cannot apply it; ship that one as a manual download and say so in the notes.

## Limits to know about

- Anyone holding the active private key, or able to approve a Publish release run, can ship an update to every user until they move to a build that no longer trusts that key. Protect your GitHub account and the spare key accordingly.
- A patch release ships the exact files CI tested. A minor or major release is a rebuild of the tested commit (the version is compiled in): the same checks run on the rebuilt files, and the release stops if the rebuild bundled different Python packages, but they are not the bytes you may have tried from the Candidate.
- Approval is the human check on what gets signed. A compromised action inside a build job could still produce bad files that you then approve; actions pinned by commit, Dependabot and CodeQL are the defence there.
- Nothing is built or tested on Linux, matching what is shipped. The Intel Mac build is smoke-tested, upgrade-tested and rehearsed, but the backend test suite runs on Windows and the Apple Silicon Mac only.
- A signature stops a forged update, not a replay of an older genuine release that is still newer than the user's version.
- If a new version migrates the database and then fails to start, the app rolls back, but the older program will refuse the newer database. The copy `updates/before-update-<version>.db` in the data folder (shown in Settings) is the recovery.
- An update interrupted between its two folder renames (the helper killed at that moment) leaves `Lit Review.old` and no `Lit Review`: rename it back (see INSTALL.md).

## Still to prove on real machines (not testable on a development PC)

- Windows: that a downloaded-by-the-app update raises no SmartScreen prompt, and whether **Smart App Control** (Windows Security, App and browser control) blocks the unsigned build. If it is on for a user, signing the Windows build is required regardless of the updater (for example Azure Trusted Signing).
- Both: the browser-based install at launch (automatic installing on): the app opens as usual, the page shows "Installing the update", a new window opens with "Welcome to Lit Review X", and nothing at all appears if no browser opens (the install still happens after about 20 s). The old tab should turn into "Lit Review was updated" with an OK button within a few seconds (same port), or become closable after a minute (different port).
- Both: a required update (Publish release with required_update ticked) and a deliberately broken update to see the rollback message.
- The app window (`backend/desktop_window.py`), on the packaged build. **Windows** (already checked from source on
  Windows 10: the window opens signed in, X hides it and the process keeps running, the first-hide notice is saved
  once, a second launch and `/api/window/show` bring it back in front, a minimized window is restored, a sign-out
  query is answered "OK to end the session" and the window still hides after that sign-out is cancelled, the tray's
  Quit ends `main()` cleanly, and the right-click menu is on with developer tools and browser keys off): still to
  see the frozen build do the same; Export (CSV, RIS, BibTeX) and Download backup show a Save dialog and write a
  correct file; Restore's file picker; right-click Copy and Paste in a text box; a paper link opens in the default
  browser; a real sign-out and shutdown with Lit Review running show no "preventing shutdown"; Install and restart
  from the window, then the welcome in the new window; an update swap is not blocked by WebView2's helper processes.
  **macOS** (nothing run on a Mac yet): the window opens and Cmd+W hides it; Dock click and the Dock menu bring it
  back; Cmd+C/V/X/A work in text boxes (pywebview's Edit menu); **Cmd+Q from inside the window asks first while a job
  runs** (pywebview's own key handler maps Cmd+Q to a stop with no question if the menu does not get it first; if
  that happens, give the app menu's Quit its own key equivalent); log out while running; the menu-bar icon; Export and
  backup through the save panel (blob downloads in WKWebView); an update install.
- Both: a computer without WebView2 (Windows) falls back to the browser with the tray working as before, and
  `/api/about` says `"shell": "browser"`.
- Windows: an automatic install of an app run from a folder inside Downloads, with Explorer open on it. A launch-time install from such a folder failed once (the cause was never recorded; a security tool or Explorer holding the folder, or a second launch during the swap, is the likely one) and left the release marked as given up for good; it is now a wait of a day (a week after later give-ups) that "Check now" ends at once, and the helper's reason (the operating system's own error text) is written to the log. Opening the app again while the helper is swapping folders can still make the swap fail (no guard against it yet). Only copies of the app that include this change protect the install that follows; one without it still needs `updates\state.json` deleted by hand.

## Proven on real machines

- The full update loop with real releases on Windows and on an Intel Mac, with automatic installing off (Install and restart) and on (applied at next launch).
- The same loop on an Apple Silicon Mac: the manual check, the automatic check, the update dialog's button and the Settings button all worked. The old OS-level "Updating Lit Review" window appeared when an update applied at startup but disappeared too fast to read (about 2 seconds on an Intel Mac, and it appeared a few seconds late), which is why launch installs now show the same "Installing the update" dialog in the browser instead. It ran from the `/Applications` folder, so the swap and relaunch work from there. The updated app was not distrusted by macOS (no Gatekeeper block or "damaged" warning) and ran straight away, so the ad hoc signature survives `ditto` extraction on Apple Silicon. No App Management permission prompt appeared during the update; it just worked. The first install (from the `.dmg`) did show macOS's "app is not trusted" warning, as expected for an unnotarized build, but the in-app update did not, because the updater downloads and extracts the app itself.
- The update rehearsal (`packaging/update_rehearsal.py`) on Windows, from the real v0.1.3 release to a local 0.1.4 build: Check now, staged, Install, the new version answering and the old folder removed.
- The whole CI/CD pipeline with v0.1.4 (November 2026): CI built and tested it on `main` (including the update rehearsal from v0.1.3 on all three platforms), Publish release with patch shipped those files, and the `sign` job (after Approve) signed it with the key from the `release` environment, published and verified it. `sign_release.py --verify v0.1.4` agreed, and installed v0.1.3 copies updated themselves to it through the app on Windows and on an Intel Mac. Not yet tried by hand: the same on an Apple Silicon Mac (CI's rehearsal passes there).
