"""Run the board reader on a still image, to check how well it copes with a given camera view.

Example (start position, White at the bottom-left corner a1 clicked first):
    python tools/read_image.py photo.jpg --color white --clicks "1800,1050 1610,163 375,160 205,1045" --out debug.png

Clicks are in player order: bottom-left, bottom-right, top-right, top-left as seen from the user's
side of the board. Use --fen for a position other than the start position.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess
import cv2
import numpy as np

from board_reader import WHITE, BoardReader, grid_to_text
from calibration import SQUARE_SIZE, WARP_SIZE, Calibration
from move_inference import _cell_name, expected_grid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--color", choices=["white", "black"], default="white")
    parser.add_argument("--clicks", required=True, help='4 "x,y" points in player order')
    parser.add_argument("--fen", default=chess.STARTING_FEN)
    parser.add_argument("--width", type=int, default=0, help="resize the image to this width first")
    parser.add_argument("--out", help="save a debug picture of the warped board")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    scale = 1.0
    if args.width:
        scale = args.width / image.shape[1]
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    clicks = [tuple(float(v) * scale for v in pair.split(",")) for pair in args.clicks.split()]
    user_color = chess.WHITE if args.color == "white" else chess.BLACK

    board = chess.Board(args.fen)
    expected = expected_grid(board, user_color)
    warped = Calibration.from_clicks(clicks).warp(image)

    reader = BoardReader()
    report = reader.learn(warped, expected)
    observed = reader.read(warped)
    wrong = np.argwhere(observed != expected)

    print(f"misread squares after learning: {report.errors} -> {[_cell_name(r, c, user_color) for r, c in wrong]}")
    print("expected:")
    print(grid_to_text(expected))
    print("observed:")
    print(grid_to_text(observed))

    if args.out:
        view = warped.copy()
        for row in range(8):
            for col in range(8):
                x, y = col * SQUARE_SIZE, row * SQUARE_SIZE
                ok = observed[row, col] == expected[row, col]
                cv2.rectangle(view, (x, y), (x + SQUARE_SIZE, y + SQUARE_SIZE), (0, 200, 0) if ok else (0, 0, 255), 1)
                value = int(observed[row, col])
                if value:
                    cv2.circle(view, (x + 10, y + 10), 6, (255, 255, 255) if value == WHITE else (0, 0, 0), -1)
                    cv2.circle(view, (x + 10, y + 10), 6, (0, 0, 255), 1)
        cv2.imwrite(args.out, view)
        print(f"saved {args.out}")


if __name__ == "__main__":
    main()
