# Installing Lit Review

You do not need to install anything else, and you never need a terminal. Lit Review is a program you download, open, and use in your web browser. It runs on your own computer.

Requirements: Windows 10 or 11, or a Mac running macOS 11 or newer. You also need an internet connection and your own API keys (see "First use" below).

## 1. Download

Open the **[latest release](https://github.com/colinpetree/lit-review/releases/latest)** page and, under **Assets**, download the file for your computer:

| Your computer | File |
|---|---|
| Windows 10 or 11 | `Lit-Review-…-Windows.zip` |
| Mac with an Apple chip (M1, M2, M3, M4 or newer) | `Lit-Review-…-macOS-Apple-Silicon.dmg` |
| Mac with an Intel chip | `Lit-Review-…-macOS-Intel.dmg` |

Not sure which Mac you have? Click the Apple menu in the top-left corner, then **About This Mac**. It says either "Chip: Apple M…" or "Processor: Intel".

The download is about 50 megabytes. (The Mac `.zip` files on the release page are for Lit Review's own update feature. You can ignore them.)

## 2. Open it for the first time

These downloads are not signed with a paid developer certificate, so your computer asks you to confirm once. This is normal for free software from outside an app store.

### Windows

1. Open your **Downloads** folder, right-click the zip, and choose **Extract All…**, then **Extract**. (Do not open the program from inside the zip: it will not work until it is extracted.) Moving the extracted **Lit Review** folder to your Documents or Desktop is fine.
2. Open the extracted folder and double-click **Lit Review**.
3. If a blue box says **"Windows protected your PC"**, click **More info**, then **Run anyway**. If your antivirus program asks, tell it to allow Lit Review.
4. Your web browser opens with Lit Review.

### Mac

1. Double-click the downloaded **.dmg** file. A window opens that shows **Lit Review** and an **Applications** folder.
2. Drag **Lit Review** onto **Applications**. (If your Mac will not let you copy into Applications, drag it to your **Documents** folder instead.)
3. Close that window, then eject the disk: in the Finder sidebar, click the small eject button next to **Lit Review** (or right-click it and choose **Eject**).
4. Open your **Applications** folder and double-click **Lit Review**. Your Mac will probably say it cannot be opened.
5. Open **System Settings**, then **Privacy & Security**, scroll down to the message about Lit Review, and click **Open Anyway**. Type your Mac password if asked, then click **Open**.
6. Your web browser opens with Lit Review. After this first time, it opens normally.

Do not open Lit Review from inside the disk window or from your Downloads folder. It will tell you to drag it into Applications first.

## 3. First use

Lit Review needs two kinds of key, both from the companies that provide the service. Open **Settings** (in the left-hand menu) and paste them in:

1. A free **OpenAlex** key (it gives you a larger daily allowance for searches).
2. A key for **one AI provider**: Anthropic (Claude), OpenAI, or Google (Gemini). The AI company charges you for what it grades, based on your use. Lit Review shows an estimate before every run and can stop a run at a limit you set in **Settings → AI Integrations**.

The other research databases (Semantic Scholar, Elsevier/Scopus, Springer Nature) are optional. Each card in Settings explains where to get its key.

Then go to **Discover Papers**, describe your research question, and follow the steps.

## Opening, closing and quitting

- Lit Review keeps running after you close its browser tab. You will see its icon near the clock (Windows, where it may be hidden behind the small **^** arrow) or in the menu bar at the top of the screen (Mac).
- To open it again, double-click **Lit Review** again (your browser opens on the copy that is already running), or use the icon's **Open Lit Review**.
- To quit, use the icon's **Quit** (on a Mac you can also press **Cmd+Q**). If it is in the middle of searching or grading, it asks first.
- Closing the tab does not stop a search or grading run that is already going, so do not quit until it is finished unless you mean to.

## Your data

Your datasets, results and prompts are kept in your own user folder, not in the program folder, so **updating or deleting the program does not delete your work**. **Settings → Software and Updates** shows the exact folder. By default:

- Windows: `C:\Users\<you>\AppData\Local\Lit Review`
- Mac: `~/Library/Application Support/Lit Review`

Your API keys are kept encrypted in that same area. Make a backup of your work from **Settings → Your Data**. API keys are deliberately not part of a backup.

## Updating

Lit Review checks for a new version by itself when it starts and then once a day, and downloads it in the background. This cannot be switched off, because the AI models it uses change and an old version can stop working. Only the program's name and version number are sent to GitHub, nothing about you or your work. Your data is kept when you update.

About once a day (and once when it is first installed), Lit Review sends the author an anonymous count that includes the software version number and operating system. It does not include any personal or identifying information like your name, your searches or your papers. This is also listed under License and Notices in Settings.

When a new version has finished downloading, Lit Review shows an **Update ready** window (and shows it again each time you start Lit Review while one is waiting). Click **Install update**: Lit Review finishes what it is doing, closes, installs the update and opens again (give it a minute). Click **Not now** (or the X, or anywhere outside the window) to put it off. The same **Install update** button is in **Settings → New versions** whenever a downloaded version is waiting, so you can install it whenever you like. If you would rather not click, turn on **Settings → New versions → Install new versions automatically**: a downloaded version is then installed the next time you open Lit Review without asking (the button in Settings still lets you do it straight away). Some updates are installed automatically the next time you open Lit Review whatever that setting says (the Update ready window then says "This update will be applied automatically on the next start", and you can still choose Install update to apply it sooner).

If the update cannot be installed, you stay on the version you have, and Lit Review says why, with a link to download the new version yourself (open the new **.dmg** and drag **Lit Review** onto **Applications**, choosing **Replace**; on Windows, extract the new zip and use the new folder). Two things stop an automatic update: running Lit Review straight from the disk image or the Downloads folder on a Mac (drag it into **Applications** first), and keeping it in a folder you are not allowed to change (move it to your Documents folder). On a newer Mac, the system may ask once whether Lit Review may modify apps: allow it in **System Settings → Privacy & Security → App Management**.

If an update is interrupted at the worst moment, the old program may be left as a folder named `Lit Review.old` next to `Lit Review` with no working `Lit Review`: rename `Lit Review.old` back to `Lit Review`.

## If something goes wrong

- **It does not open, or shows a message box:** read the message. It says what to try.
- **Windows says it cannot start or a file is missing:** make sure you extracted the whole zip (step 2 above).
- **A Mac message says Lit Review is running from the installer:** you opened it from inside the disk window or from Downloads. Drag **Lit Review** into your **Applications** folder (or Documents), eject the disk, and open it from there.
- **The browser shows "not connected":** open Lit Review again from its icon, which opens a connected window.
- **Anything else:** the log is in the **Log folder** shown in **Settings → Software and Updates**. The icon's **Open log folder** shows it. Send that file to whoever is helping you.

## Removing it

Quit Lit Review, then delete the program (the **Lit Review** folder on Windows, or **Lit Review** in Applications on a Mac). Your data stays in the data folder above until you delete that too.
