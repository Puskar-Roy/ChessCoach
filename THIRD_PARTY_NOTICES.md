# Third-party notices

| Component | Source and license |
| --- | --- |
| [`app/renderer/assets/pieces.svg`](app/renderer/assets/pieces.svg) | Chess artwork by [Cburnett](https://en.wikipedia.org/wiki/User:Cburnett) and [Rfc1394](https://en.wikipedia.org/wiki/User:Rfc1394) from [Wikimedia Commons](https://commons.wikimedia.org/wiki/Category:SVG_chess_pieces/Standard), modified by shaack for [cm-chessboard](https://github.com/shaack/cm-chessboard), under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). See the attribution embedded in the SVG. |
| Chess rules and UCI client | [python-chess](https://github.com/niklasf/python-chess), GPL-3.0-or-later; installed as the `chess` Python package. |
| Chess engine | [Stockfish](https://github.com/official-stockfish/Stockfish) 19, GPL-3.0. The executable is not in this repository; release builds bundle the unmodified official binary (`stockfish-windows-x86-64-universal.exe`) together with its `Copying.txt`. Its complete source code is at https://github.com/official-stockfish/Stockfish. |
| Python runtime and packaging | [CPython](https://www.python.org/) (PSF license) and [PyInstaller](https://pyinstaller.org/) (GPL-2.0-or-later with a bootloader exception that permits bundling non-GPL and GPL programs); release builds contain the frozen backend. |
| Vision libraries | [OpenCV](https://opencv.org/) (Apache-2.0) and [NumPy](https://numpy.org/) (BSD-3-Clause), bundled in release builds. |
| Desktop runtime | [Electron](https://github.com/electron/electron), MIT with its own third-party notices; installed by npm. |

Other dependencies installed by pip and npm retain their upstream licenses. ChessCoach is not
affiliated with Chess.com or Lichess. See [the model notes](models/README.md) for the piece
recognizer's training-data status.
