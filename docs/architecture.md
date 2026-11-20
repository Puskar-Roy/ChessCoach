# Architecture

## Desktop and Python backend

`ChessCoach.bat` starts Electron. [`app/main.js`](../app/main.js) owns the main window, board picker,
dock, and overlay. The renderer is plain HTML, CSS, and JavaScript. It calls the main process through
[`app/preload.js`](../app/preload.js) and renders state from an observable store. The UI uses spring
motion for interactive changes and respects the system's reduced-motion setting.

[`app/python.js`](../app/python.js) starts [`bridge.py`](../bridge.py). They exchange newline-delimited
JSON on standard input and output. The bridge dispatches requests and relays events from
[`controller.py`](../controller.py), which runs one game session on a background thread. Keep backend
diagnostic output on stderr so it cannot break the protocol.

The controller uses `python-chess` for legal moves and game state, and Stockfish for analysis.
[`coach.py`](../coach.py) turns that analysis into move feedback; [`trainer.py`](../trainer.py) adds
opening plans from [`repertoire.py`](../repertoire.py). The command-line entry point, [`main.py`](../main.py),
uses the coaching code directly and does not start Electron.

## Screen reading

1. [`screen_capture.py`](../screen_capture.py) captures a monitor and [`board_detect.py`](../board_detect.py)
   finds candidate board rectangles. The board picker lets the user confirm the region.
2. [`screen_reader.py`](../screen_reader.py) learns what empty, white-occupied, and black-occupied squares
   look like on the selected board. For games already in progress, [`piece_cluster.py`](../piece_cluster.py)
   and [`piece_classifier.py`](../piece_classifier.py) help reconstruct a starting position the user can correct.
3. [`watcher.py`](../watcher.py) waits for a stable image and samples multiple frames.
   [`vision_infer.py`](../vision_infer.py) scores legal continuations against the observed squares.
   An ambiguous result is reported as unclear instead of being applied as a move.

The overlay is click-through. Electron requests that Windows exclude ChessCoach's own windows from
capture so the overlay and dock don't interfere with board recognition.
