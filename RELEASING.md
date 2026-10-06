# Releasing Lit Review

Releases are built by GitHub Actions from a tag, and every release is **signed by you** before the in-app updater will offer it. The signing key lives offline, never in this repository or in a GitHub secret.

## One-time setup

1. Make the keys, outside the repository, on a computer you trust:

   ```
   python packaging/make_update_key.py --active D:\keys\lit-review-active.pem --spare E:\keys\lit-review-spare.pem
   ```

   It asks for a passphrase for each key and prints a `PUBLIC_KEYS = [...]` block.
2. Paste that block over `PUBLIC_KEYS` in `backend/update_manifest.py` and commit it. Only the public keys go in the app.
3. Keep the **spare** key somewhere different from the active one (not the same password-manager entry or computer). If the active key is lost or leaked, the spare signs an ordinary release that carries a new key list.
4. Install the GitHub CLI (`gh`) and sign in (`gh auth login`). `sign_release.py` uses it.

Until `PUBLIC_KEYS` is filled in, no manifest verifies and the app never offers an update.

## Every release

1. Push a tag: `git tag v0.1.1 && git push origin v0.1.1`. The workflow builds the Windows zip, the two Mac zips and disk images, `SHA256SUMS.txt` and an **unsigned** `update-manifest.json`, into a **draft** release.
2. Try the downloads from the draft.
3. Sign it:

   ```
   python packaging/sign_release.py v0.1.1 --key D:\keys\lit-review-active.pem
   ```

   It re-downloads the zips, checks each one against the manifest (so a zip swapped after the build is never signed), asks for the passphrase, signs, checks the signature against the keys built into the app, and uploads `update-manifest.json.sig`.
4. Publish the draft on GitHub. (A draft is invisible to the app. So is a pre-release.)
5. Check it: `python packaging/sign_release.py --verify v0.1.1`. Do this after every publish.

Pulling a bad release (delete it) stops it being offered. The next fixed release needs a higher version number.

## A release that old versions can no longer survive

If a retired AI model, or something like it, means old versions stop working, raise the floor:

```
python packaging/sign_release.py v0.1.2 --key ... --min-version 0.1.2 --notice "The AI model Lit Review used was retired."
```

Every copy older than `--min-version` then treats the update as required: it downloads in the background, installs at the next start whatever the "install automatically" setting says, and shows the ordinary Update ready window when it finishes ("There is an update that is ready to install. This update will be applied automatically on the next start."). Nothing in the app calls it required, and it never blocks the app, so people can still reach their data. **Rehearse the update path first**: a floor raised on a release whose install fails leaves everyone on the old version, with a banner explaining that the update could not be installed and a link to download it.

## What the updater needs from a release

- The three platform zips, named `Lit-Review-<version>-Windows.zip`, `-macOS-Apple-Silicon.zip`, `-macOS-Intel.zip`. The `.dmg` files are for people and are never listed in the manifest.
- A **public** repository, a **published** (not draft) release, and a signature that verifies. Anything else, and the app silently offers nothing.
- If a release changes the install layout (a different folder structure inside the zip), the updater cannot apply it; ship that one as a manual download and say so in the notes.

## Limits to know about

- Anyone holding the active private key can ship an update to every user until they move to a build that no longer trusts it. Protect it like a bank password.
- A signature stops a forged update, not a replay of an older genuine release that is still newer than the user's version.
- If a new version migrates the database and then fails to start, the app rolls back, but the older program will refuse the newer database. The copy `updates/before-update-<version>.db` in the data folder (shown in Settings) is the recovery.
- An update interrupted between its two folder renames (the helper killed at that moment) leaves `Lit Review.old` and no `Lit Review`: rename it back (see INSTALL.md).

## Still to prove on real machines (not testable on a development PC)

- Windows: that a downloaded-by-the-app update raises no SmartScreen prompt, and whether **Smart App Control** (Windows Security, App and browser control) blocks the unsigned build. If it is on for a user, signing the Windows build is required regardless of the updater (for example Azure Trusted Signing).
- macOS Apple Silicon: the whole update loop (see below), which has not been run on an Apple Silicon Mac yet.
- macOS: that the swap and relaunch work from `/Applications`, whether the App Management permission prompt appears on macOS 13 or newer (and how often), and that the ad hoc signature survives `ditto` extraction.
- Both: a forced `--min-version` run and a deliberately broken update to see the rollback message.

## Proven on real machines

- The full update loop with real releases on Windows and on an Intel Mac, with automatic installing off (Install and restart) and on (applied at next launch).
