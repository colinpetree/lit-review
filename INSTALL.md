# Installing Lit Review

You do not need to install anything else, and you never need a terminal. Lit Review is a program you download, open, and use in your web browser. It runs on your own computer.

Requirements: Windows 10 or 11, or a Mac running macOS 11 or newer. You also need an internet connection and your own API keys (see "First use" below).

## 1. Download

Open the **[latest release](https://github.com/colinpetree/lit-review/releases/latest)** page and, under **Assets**, download the file for your computer:

| Your computer | File |
|---|---|
| Windows 10 or 11 | `Lit-Review-…-windows.zip` |
| Mac with an Apple chip (M1, M2, M3, M4 or newer) | `Lit-Review-…-macos-apple-silicon.zip` |
| Mac with an Intel chip | `Lit-Review-…-macos-intel.zip` |

Not sure which Mac you have? Click the Apple menu in the top-left corner, then **About This Mac**. It says either "Chip: Apple M…" or "Processor: Intel".

The download is a few hundred megabytes.

## 2. Open it for the first time

These downloads are not signed with a paid developer certificate, so your computer asks you to confirm once. This is normal for free software from outside an app store.

### Windows

1. Open your **Downloads** folder, right-click the zip, and choose **Extract All…**, then **Extract**. (Do not open the program from inside the zip: it will not work until it is extracted.) Moving the extracted **Lit Review** folder to your Documents or Desktop is fine.
2. Open the extracted folder and double-click **Lit Review**.
3. If a blue box says **"Windows protected your PC"**, click **More info**, then **Run anyway**. If your antivirus program asks, tell it to allow Lit Review.
4. Your web browser opens with Lit Review.

### Mac

1. Double-click the zip to extract it. Drag **Lit Review** into your **Applications** folder.
2. Double-click **Lit Review** in Applications. Your Mac will probably say it cannot be opened.
3. Open **System Settings**, then **Privacy & Security**, scroll down to the message about Lit Review, and click **Open Anyway**. Type your Mac password if asked, then click **Open**.
4. Your web browser opens with Lit Review. After this first time, it opens normally.

## 3. First use

Lit Review needs two kinds of key, both from the companies that provide the service. Open **Settings** (in the left-hand menu) and paste them in:

1. A free **OpenAlex** key (it gives you a larger daily allowance for searches).
2. A key for **one AI provider**: Anthropic (Claude), OpenAI, or Google (Gemini). The AI company charges you for what it scores, based on your use. Lit Review shows an estimate before every run and can stop a run at a limit you set in **Settings → AI Integrations**.

The other research databases (Semantic Scholar, Elsevier/Scopus, Springer Nature) are optional. Each card in Settings explains where to get its key.

Then go to **Discover Papers**, describe your research question, and follow the steps.

## Opening, closing and quitting

- Lit Review keeps running after you close its browser tab. You will see its icon near the clock (Windows, where it may be hidden behind the small **^** arrow) or in the menu bar at the top of the screen (Mac).
- To open it again, double-click **Lit Review** again (your browser opens on the copy that is already running), or use the icon's **Open Lit Review**.
- To quit, use the icon's **Quit** (on a Mac you can also press **Cmd+Q**). If it is in the middle of searching or scoring, it asks first.
- Closing the tab does not stop a search or scoring run that is already going, so do not quit until it is finished unless you mean to.

## Your data

Your datasets, results and prompts are kept in your own user folder, not in the program folder, so **updating or deleting the program does not delete your work**. **Settings → About and Updates** shows the exact folder. By default:

- Windows: `C:\Users\<you>\AppData\Local\lit-review\lit-review`
- Mac: `~/Library/Application Support/lit-review`

Your API keys are kept encrypted in that same area. Make a backup of your work from **Settings → Your Data**. API keys are deliberately not part of a backup.

## Updating

When a new version is available, Lit Review shows a notice at the top of the page with a link. To update: quit Lit Review, download the new version the same way, and replace the old program with it. Your data is kept. (This check can be turned off in **Settings → New versions**. It sends only the program name and version number to GitHub.)

## If something goes wrong

- **It does not open, or shows a message box:** read the message. It says what to try.
- **Windows says it cannot start or a file is missing:** make sure you extracted the whole zip (step 2 above).
- **The browser shows "not connected":** open Lit Review again from its icon, which opens a connected window.
- **Anything else:** the log is in the **Log folder** shown in **Settings → About and Updates**. The icon's **Open log folder** shows it. Send that file to whoever is helping you.

## Removing it

Quit Lit Review, then delete the program (the **Lit Review** folder on Windows, or **Lit Review** in Applications on a Mac). Your data stays in the data folder above until you delete that too.
