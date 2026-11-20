# Setup guide

Everything you need to install, run, test and package ChessCoach on Windows, written for someone who
has never set up a Python or Electron project before. Follow the steps in order; each one says how to
check that it worked.

If you want to understand *how* the program works rather than how to install it, read
[Architecture](architecture.md).

**Contents**

1. [Pick your path](#1-pick-your-path)
2. [What you need](#2-what-you-need)
3. [Install the tools](#3-install-the-tools)
4. [Get the code and install it](#4-get-the-code-and-install-it)
5. [Run ChessCoach](#5-run-chesscoach)
6. [Your first game from the screen](#6-your-first-game-from-the-screen)
7. [Check that everything works](#7-check-that-everything-works)
8. [Build the installer and the single-file exe](#8-build-the-installer-and-the-single-file-exe)
9. [The command-line version](#9-the-command-line-version)
10. [Where ChessCoach stores things](#10-where-chesscoach-stores-things)
11. [Troubleshooting](#11-troubleshooting)
12. [Updating and uninstalling](#12-updating-and-uninstalling)

> **Fair play.** ChessCoach is for practice, analysis and study. Do not use live coaching in games
> where outside help is forbidden, such as rated online matches. It never plays moves for you on a
> website.

---

## 1. Pick your path

| I want to... | Do this |
| --- | --- |
| **Just use the app** (someone gave me the installer) | Run `ChessCoach-Setup-x.y.z.exe`, or the portable `ChessCoach-x.y.z-portable.exe`. Nothing else to install. Skip to [section 6](#6-your-first-game-from-the-screen). Windows may show a "protected your PC" warning because the file is not code-signed: choose *More info* then *Run anyway*. |
| **Run it from the source code** (to try it or change it) | Sections 2 to 7. |
| **Build my own installer** | Sections 2 to 4 first, then [section 8](#8-build-the-installer-and-the-single-file-exe). |

## 2. What you need

| Requirement | Version | Why |
| --- | --- | --- |
| Windows | 10 or 11, 64-bit | Screen capture exclusion, speech and the installer are Windows features. Windows 11 also gives the app a translucent look; Windows 10 gets a solid one. |
| Python | **3.12** | The "brain": vision, chess rules and coaching. |
| Node.js | **22.12 or newer** | Installs and runs the Electron desktop app. (Node 20 is too old for the Electron version used.) |
| Stockfish | any 64-bit Windows build | The chess engine. It is a separate download. |
| Internet | for the first install only | To download Python packages, Electron (about 100 MB) and, if you build a release, the installer tooling. Playing needs no internet. |
| Disk space | about 1.5 GB for a development checkout; about 2 GB more while building a release | |
| Git | optional | Only to download the code with `git clone`. You can also download a ZIP. |

You do **not** need a webcam, a GPU, an account, or any API key.

## 3. Install the tools

Skip any tool you already have at the right version. Open **PowerShell** (press the Windows key,
type `powershell`, press Enter) to run the check commands.

### 3.1 Python 3.12

1. Download the Windows installer for Python 3.12 from <https://www.python.org/downloads/>.
2. In the installer, tick **"Add python.exe to PATH"** before pressing *Install Now*.
3. Check:
   ```powershell
   py -3.12 --version
   ```
   It should print `Python 3.12.x`. (If `py` is not found, close and reopen PowerShell.)

### 3.2 Node.js 22.12 or newer

Two ways; pick one.

* **Simplest:** install the current LTS from <https://nodejs.org/> if it is version 22.12 or newer.
* **If you need several Node versions** (for example another project needs Node 20): install
  [nvm-windows](https://github.com/coreybutler/nvm-windows/releases), then:
  ```powershell
  nvm install 22
  nvm use 22
  ```
  The file `.nvmrc` in the project also says `22`.

Check (open a **new** PowerShell window first):
```powershell
node --version
npm --version
```
`node` must print `v22.12.0` or higher.

### 3.3 Stockfish

1. Go to <https://stockfishchess.org/download/> and download the **Windows** build. Any 64-bit build
   works. The "universal" build runs on every CPU; the AVX2 build is a little faster on modern CPUs.
2. Unzip it. Remember the path of the `stockfish...exe` inside.

You will tell ChessCoach where it is in [step 4.4](#44-tell-chesscoach-where-stockfish-is).

### 3.4 Git (optional)

Install from <https://git-scm.com/download/win> if you want to use `git clone`. Otherwise you can
download the project as a ZIP and unzip it.

## 4. Get the code and install it

Everything below is run in PowerShell, from the project folder (the one that contains `README.md`).

### 4.1 Get the code

```powershell
git clone <the repository address> chess-assistant
cd chess-assistant
```
(or unzip the download and `cd` into the unzipped folder).

### 4.2 Create the Python environment

A **virtual environment** is a private folder of Python packages for this project, so it cannot
clash with anything else on your computer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs what the app needs (`chess`, `opencv-python`, `numpy`, `mss`,
`pyttsx3`, `comtypes`) plus what the tests need (`pytest`, `pillow`). It takes a minute or two.

Check:
```powershell
.\.venv\Scripts\python.exe -c "import chess, cv2, numpy, mss; print('python packages ok')"
```

> If PowerShell refuses to run scripts, you never need to "activate" the environment in this guide:
> every command calls `.\.venv\Scripts\python.exe` directly.

### 4.3 Install the desktop app

```powershell
npm --prefix app ci
```

This installs Electron (the desktop shell). It downloads about 100 MB the first time. Check:
```powershell
Test-Path app\node_modules\electron\dist\electron.exe
```
It should print `True`.

### 4.4 Tell ChessCoach where Stockfish is

ChessCoach looks for Stockfish in this order. Use whichever is easiest:

1. **Put it inside the project (easiest).** Create the folder `bin` in the project folder and unzip
   Stockfish there. Any subfolder is fine; ChessCoach searches `bin\**\stockfish*.exe`.
2. **Set an environment variable** with the full path of the exe (for your user, permanently):
   ```powershell
   setx STOCKFISH_PATH "C:\Tools\stockfish\stockfish-windows-x86-64-avx2.exe"
   ```
   Then close and reopen PowerShell.
3. **Put `stockfish.exe` on your `PATH`.**

Check:
```powershell
.\.venv\Scripts\python.exe -c "from engine import find_stockfish; print(find_stockfish())"
```
It should print the path to the exe. If it prints "Stockfish not found", see
[troubleshooting](#11-troubleshooting).

### 4.5 The piece-recognition model (not provided)

`models\pieces.npz` would be a small file (about 1.4 MB) that lets ChessCoach recognise pieces when
you join a game that is **already under way**. **This model is not provided with ChessCoach**: it is
not in the repository (`/models/*.npz` is git-ignored) and it is not in shared builds. You do not need
to do anything about it.

* **What works without it (everything you will normally use):** typed moves, and following a game from
  the screen **when you start it at the starting position**, including grading, advice, openings,
  quick replies, missed moves and takebacks.
* **What does not work:** joining a game that is already in progress. If you select a board that is
  mid-game, the app says "Joining a game in progress is not available in this version" and asks for a
  new game. It also cannot rebuild a whole position from the screen if it loses a game completely;
  press **Re-read**, type the move, or start a new game.
* **If you want to experiment:** you can train a recogniser of your own with `tools\train_pieces.py`
  (see [`models/README.md`](../models/README.md); needs `requirements-training.txt` and a folder of
  piece pictures you are allowed to use) and put the result at `models\pieces.npz`. Mid-game joining
  then switches on by itself.

## 5. Run ChessCoach

Double-click **`ChessCoach.bat`**, or run:

```powershell
npm --prefix app start
```

The window should open in a few seconds. In development the app starts the Python backend from your
`.venv` automatically; there is nothing else to launch. To see any messages from the backend, run the
second command from PowerShell and watch the window it was started from.

## 6. Your first game from the screen

1. **Open a chess website** (any site, a bot game or an analysis board) and keep the whole board
   visible. Scroll so nothing covers it. **Start a new game**, so the board shows the starting position
   when you select it (joining a game that is already under way is
   [not available in this version](#45-the-piece-recognition-model-not-provided)).
2. In ChessCoach, open **Play**, choose **From my screen**, then press **Start**.
3. The screen dims and ChessCoach highlights the board it found. If the highlight is a little off,
   drag a corner or drag the whole square. Keyboard: **Enter** confirms, **Esc** cancels, **R**
   takes a new screenshot, **Tab** switches between several boards. Press **Use this board**.
4. ChessCoach learns what your board looks like (a second or two). It uses the starting position
   as the answer sheet, learns your site's colours and pieces, and tells you which side you are on.
   If the board is already mid-game, it tells you that joining a game in progress is not available in
   this version; start a new game and press **Retake**.
5. The main window hides, a narrow **dock** appears next to your board, and an **arrow** is drawn on your
   real board for the suggested move. Play on the website as usual. ChessCoach follows every move
   you and your opponent make, grades yours, and explains the advice.

During a game the dock offers:

| Button | What it does |
| --- | --- |
| **Hint** | Reveals the coach's suggestion (useful in Practice and Test modes). |
| **Re-read** | Look at the board again. Use it if a move was missed. |
| **Undo** | Takes the last move back (take it back on the website as well). |
| **New** | Starts over. |
| **Type a move** | If a move was not read, type it, for example `Nf3` or `e5`. |
| **Switch side / Fix pieces** | Only appear in builds that include the optional piece model and joined a game in progress. |

Tips for good reading:

* Keep the board **fully visible** and do not move the window while playing (small moves are
  tolerated; the board is found again).
* **Do not cover the board** with other windows.
* Holding a piece with the mouse is fine. ChessCoach waits until you let go.
* If the board is on another monitor, open **Settings** (bottom left) and set **Screen to watch**.
* In **Settings** you can also change the thinking time, turn voice and arrows on or off, and pick
  the board colours of the in-app board. Under **Openings** you can choose an opening system and a
  level (Guided, Practice, Test).

## 7. Check that everything works

### Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

About three minutes. Tests that need Stockfish or the piece model are skipped if those are missing,
so "passed" plus a few "skipped" is normal. Anything marked "failed" is worth a look.

### Check the engine and model by hand

```powershell
.\.venv\Scripts\python.exe -W ignore -c "import io, json, bridge; print(json.dumps(bridge.Bridge(io.StringIO()).handle('app.selftest', {}), indent=2))"
```

This prints a report for the engine, opening book, vision, screen capture and voice (and whether the
optional piece model is present: `"present": false` is expected). It should show `"ok": true` at the top. (In an installed app, the same report is produced by
`ChessCoach.exe --self-test`.)

## 8. Build the installer and the single-file exe

This turns the project into files you can give to anyone: an **installer** and a **portable single
`.exe`**, with Python, the backend and Stockfish all inside.

**Before you start** you need sections 3 and 4 done, plus:

* Stockfish under `bin\` (or `CHESSCOACH_STOCKFISH` set to its path): it is bundled into the app;
* the build tools:
  ```powershell
  .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
  ```

**Build:**

```powershell
.\.venv\Scripts\python.exe tools\build_release.py
```

It runs four stages and prints each command:

1. makes the app icon if it is missing;
2. freezes the Python backend with PyInstaller into `build\dist\backend`;
3. packages the Electron app plus that backend with electron-builder (the first run also downloads
   the installer tooling);
4. starts the packaged app in self-test mode and checks that everything inside it works.

The first build takes roughly 5 to 10 minutes. The results are in **`release\`**:

| File | Use it when |
| --- | --- |
| `ChessCoach-Setup-1.0.0.exe` | Normal distribution. Installs per user (no administrator rights), adds Start menu and desktop shortcuts and an uninstaller. Starts fastest. |
| `ChessCoach-1.0.0-portable.exe` | One file to carry on a USB stick. It unpacks itself every time it starts, so launch takes about 15 to 20 seconds. |
| `win-unpacked\ChessCoach.exe` | The unpacked folder both are made from; handy for testing. |

Handy options:

```powershell
.\.venv\Scripts\python.exe tools\build_release.py --dir            # only the unpacked folder (faster)
.\.venv\Scripts\python.exe tools\build_release.py --skip-backend   # reuse the backend from the last run
.\.venv\Scripts\python.exe tools\build_release.py --no-selftest    # skip the final self-test
```

**Check a finished build** by running the packaged program in self-test mode:

```powershell
.\release\win-unpacked\ChessCoach.exe --self-test
```

It prints a JSON report and exits with code 0 when everything inside is present and working.

**Before you share the installer:** it is not code-signed, so Windows SmartScreen will warn on first
run until you sign it with a certificate. **Build shared installers with `--no-model`** so the piece
model is never inside them, even if you have the file on your machine:
`.\.venv\Scripts\python.exe tools\build_release.py --no-model`. Stockfish is GPL-3
software bundled unmodified; its licence text and source link are listed in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## 9. The command-line version

There is also a version without the desktop window, which prints advice in the terminal:

```powershell
.\.venv\Scripts\python.exe main.py --color white            # type moves yourself
.\.venv\Scripts\python.exe main.py --color white --camera   # read a physical board with a webcam
.\.venv\Scripts\python.exe main.py --screen                 # follow a board on your screen
```

Add `--help` to see all options.

## 10. Where ChessCoach stores things

| Item | Location |
| --- | --- |
| Settings, game history, diagnostics | `%APPDATA%\ChessCoach\` (paste that into the File Explorer address bar) |
| Boards that could not be read | `%APPDATA%\ChessCoach\debug\unclear-*.png` (only the board, the newest 12) and `debug.log` |
| Opening book (shipped with the app) | `data\openings.json` |
| Camera calibration (command-line camera mode only) | `data\calibration.json` |

Nothing is uploaded anywhere. To reset the app completely, close it and delete the
`%APPDATA%\ChessCoach` folder. Review the files in `debug` before sharing them with anyone: a board
picture shows your pieces and possibly player names if the site draws them inside the board.

## 11. Troubleshooting

| What you see | Why, and what to do |
| --- | --- |
| `npm ci` or `npm install` fails with an "engine" or Node version message | Your Node is older than 22.12. Install a newer one ([section 3.2](#32-nodejs-2212-or-newer)), open a **new** PowerShell window, check `node --version`, and run `npm --prefix app ci` again. |
| The app starts but nothing happens / "The coach engine is not running" | The Python backend did not start. Make sure `.venv` exists ([step 4.2](#42-create-the-python-environment)). Run `.\.venv\Scripts\python.exe bridge.py` from PowerShell: it should print a line starting with `{"event":"ready"`. Any red text before that shows the problem. |
| "Stockfish not found" | Follow [step 4.4](#44-tell-chesscoach-where-stockfish-is). Check with the `find_stockfish` command there. If you set `STOCKFISH_PATH` with `setx`, close and reopen PowerShell first. |
| `ChessCoach.bat` says it needs a virtual environment | You have not done [step 4.2](#42-create-the-python-environment) in this folder. |
| "I couldn't find a board by myself" | The board is too small, partly covered, or very unusual. Drag a rectangle around the 8 x 8 squares yourself in the picker. Zoom the website in a little. |
| "I could not tell N squares apart" when confirming | Part of the board is covered or the rectangle is off. Retake the screenshot (**R**) and make sure nothing overlaps the board. |
| It says the game is "already under way" but you started a new one | The site was not yet showing the start position when you confirmed (for example the pieces were still sliding in). Press **Retake**. |
| "I couldn't tell what changed" keeps appearing | Something is covering the board, a piece is mid-drag, or the site shows an unusual overlay. Release the mouse, make the board visible and press **Re-read**. If it persists, type the move. Look at `%APPDATA%\ChessCoach\debug` for the picture it could not read. |
| "Joining a game in progress is not available in this version" | Expected: the piece-recognition model is not provided ([step 4.5](#45-the-piece-recognition-model-not-provided)). Start a new game, then select the board while it shows the starting position. |
| The board is on another monitor and is not found | **Settings**, then **Screen to watch**, and choose that screen. |
| No voice | Windows has no speech voice installed or the sound is muted. Turn the voice off in Settings; everything else still works. |
| Windows says "protected your PC" for the installer | The installer is not code-signed. Choose *More info*, then *Run anyway*, only if you trust where you got it. |
| Antivirus quarantines the built `.exe` | Programs made with PyInstaller are sometimes flagged by mistake. Add an exception, or sign the build. |
| The build stops while electron-builder extracts something and mentions symbolic links | Turn on Windows **Developer Mode** (Settings, System, For developers) or run PowerShell as administrator once, then build again. |
| The self-test reports `screen: null` | The build ran without an interactive desktop (for example over a remote session or a service). Run it from a normal signed-in desktop. |

## 12. Updating and uninstalling

* **From source:** get the new code (`git pull`), then rerun
  `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` and `npm --prefix app ci`
  in case dependencies changed.
* **Installed app:** run the new installer over the old one; settings are kept.
* **Uninstall:** *Settings, Apps*, then ChessCoach, or run the uninstaller in the install folder.
  Your settings and history are kept in `%APPDATA%\ChessCoach`; delete that folder to remove them.
  The portable file leaves nothing behind except that data folder.
