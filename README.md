# Lit Review

A program for finding and sorting scientific papers on your own computer. You describe your research question, Lit Review searches scholarly databases (OpenAlex, PubMed, Semantic Scholar, Scopus), and an AI model of your choice grades each paper's abstract against what you are looking for, so the most relevant ones come first. It works for a one-off literature review and for checking a field for new papers every so often.

It is for any STEM researcher or graduate student. Nothing about it is tied to one field.

## Download

Go to the **[latest release](https://github.com/colinpetree/lit-review/releases/latest)** and download the file for your computer (Windows, Mac with an Apple chip, or Mac with an Intel chip). The step-by-step guide, including what to do the first time your computer asks you to confirm, is in **[INSTALL.md](INSTALL.md)**.

## Your data stays on your computer

- Everything runs on your own computer and is reachable only from it. There is no account and no server of ours.
- Your datasets, results and prompts are stored in a file in your user folder. Your API keys are stored encrypted, in a separate settings folder.
- The only things that leave your computer are the searches you run (sent to the paper databases you choose), the paper titles and abstracts you ask the AI model to grade (sent to the AI company whose key you entered), and, optionally, a once-a-day check for a new version of Lit Review (it can be turned off in Settings).
- You pay the AI company directly, using your own key. Lit Review shows an estimate before every run and stops a run at a limit you control.

## For developers

See [CLAUDE.md](CLAUDE.md) for how the code is organized and the commands to run it from source, and [PLAN.md](PLAN.md) for the design. Released builds are made by `.github/workflows/release.yml`.

Lit Review is free to use for any purpose, including at work, and the source is public. It is released under the [Functional Source License, Version 1.1, MIT Future License](LICENSE) (FSL-1.1-MIT): you may use, modify and share it, but you may not use it to offer a competing commercial product or service. Each version becomes plain MIT two years after its release. The licenses of the software it includes are listed in the app under **Settings → License and Notices**, and are also inside the app as `licenses/THIRD_PARTY_NOTICES.txt` (on Windows in the `_internal` folder next to `Lit Review.exe`).
