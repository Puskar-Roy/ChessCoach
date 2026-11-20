# ChessCoach

ChessCoach is a local Windows chess coach for practice and analysis. It explains Stockfish
recommendations, grades moves, and teaches opening plans such as the London System, English Opening,
and Caro-Kann. Use the built-in board or let it follow a board on your screen.

**Fair play:** Use live coaching only where outside assistance is explicitly allowed, such as
offline practice or a study board. Do not use it during online matches that prohibit engine help.
ChessCoach does not make moves in other apps or websites.

## Run from source

You need Windows 10 or 11, [Python 3.12](https://www.python.org/downloads/),
[Node.js 22.12 or later](https://nodejs.org/), and [Stockfish](https://stockfishchess.org/download/).

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix app ci
```

Extract the Stockfish download under `bin/`, put `stockfish.exe` on `PATH`, or set `STOCKFISH_PATH`
to the executable's full path. Then double-click `ChessCoach.bat` or run `npm --prefix app start`.

## Use ChessCoach

- **On this board:** Enter moves for either side and get explanations, evaluations, and move grades.
- **From my screen:** Choose **Select my board**, confirm the detected board, and let ChessCoach
  follow the moves. For a game already in progress, review the position and correct any misread
  pieces, or supply a FEN in Settings. The optional piece-classification model is not bundled until
  its training assets are cleared for redistribution, so mid-game recognition may require you to
  identify piece groups yourself. Automatic recovery after the live board drifts out of sync also
  needs that model; restart the session or re-enter the position instead. Moves before you joined
  are not recovered.
- **Openings:** Pick an opening plan and choose Guided, Practice, or Test mode to control when
  advice is revealed. Review saved game statistics in **Progress**.

Chess analysis and screen capture run on your computer. The board picker captures the selected
monitor to locate the board. The app saves settings, game history, and diagnostic logs in its local
Electron profile; failed reads can also save a cropped board image there. Review those files before
sharing them with a bug report. The CLI saves its calibration under `data/` by default.

## Command line

The CLI still supports typed moves, a physical board, and a board on screen:

```powershell
.\.venv\Scripts\python.exe main.py --color white
.\.venv\Scripts\python.exe main.py --color white --camera
.\.venv\Scripts\python.exe main.py --screen
```

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

See [Contributing](CONTRIBUTING.md) for optional hardware tests and vision tools,
[Architecture](docs/architecture.md) for a code map, [Third-party notices](THIRD_PARTY_NOTICES.md)
for asset and dependency attribution, and [Model notes](models/README.md) for the optional recognizer.
