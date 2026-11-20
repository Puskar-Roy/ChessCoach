# Contributing

Follow the [setup guide](docs/setup.md) (or [the short version](README.md#run-from-source)), read [how it works](docs/architecture.md), then install `requirements-dev.txt` and run
the Python tests. Most vision tests use synthetic boards, so you do not need a camera or an
interactive desktop. Tests that need Stockfish skip if the executable is not installed.

## Testing changes

- For screen capture changes, run the Windows desktop test from a signed-in desktop:
  ```powershell
  $env:CHESSCOACH_TEST_DESKTOP = '1'
  .\.venv\Scripts\python.exe -m pytest tests/test_bridge.py
  Remove-Item Env:CHESSCOACH_TEST_DESKTOP
  ```
- `tests/test_real_screen.py` optionally uses locally supplied `tests/data/chesscom_start_black.png`
  and `tests/data/chesscom_midgame_black.png`. It skips if both are absent. Do not commit these
  files or attach private screenshots to issues.
- For UI changes, launch the app and check both manual and screen modes. `app/devscript.js` can
  script local UI checks; only supply scripts you trust.
- To benchmark move detection, run `python tools/benchmark_vision.py` from the activated virtual
  environment. For classifier training and benchmarking, install `requirements-training.txt` and
  see [the model notes](models/README.md).

For a bug report, include your Windows version, the steps to reproduce, the expected and actual
behavior, and whether you were using the built-in board, screen mode, or the CLI. If sharing logs
or screenshots, remove personal information first. For a pull request, describe the change and
include relevant test results.
