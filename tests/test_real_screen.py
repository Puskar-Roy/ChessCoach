"""Regression test on real chess.com screenshots (board seen from Black's side)."""

from pathlib import Path

import chess
import cv2
import numpy as np
import pytest

from board_reader import BLACK, EMPTY, WHITE, BoardReader
from move_inference import expected_grid

DATA = Path(__file__).parent / "data"

# Midgame screenshot, last-move squares highlighted yellow. Row 0 is rank 1 (Black sits at the bottom).
MIDGAME = """
W . W . W W . W
W W W . . W W W
. . . . . . . .
. . . W b . . .
. W . b W . . .
. . b . . . . .
b b b . . b b b
b . b b b . . b
"""


def parse(text):
    symbols = {".": EMPTY, "W": WHITE, "b": BLACK}
    return np.array([[symbols[t] for t in row.split()] for row in text.strip().splitlines()])


@pytest.fixture(scope="module")
def screenshots():
    paths = [DATA / name for name in ("chesscom_start_black.png", "chesscom_midgame_black.png")]
    if not any(path.exists() for path in paths):
        pytest.skip("optional local screenshots are not installed")
    images = [cv2.imread(str(path)) for path in paths]
    assert all(image is not None for image in images), "both screenshot fixtures must be readable"
    return images


def test_highlighted_squares_on_a_real_site_are_read_correctly(screenshots):
    start, midgame = screenshots
    reader = BoardReader(augment=True)
    report = reader.learn(start, expected_grid(chess.Board(), chess.BLACK))
    assert report.errors == 0
    observed = reader.read(midgame)
    assert (observed == parse(MIDGAME)).all()


def test_the_screen_reader_handles_the_same_real_screenshots(screenshots):
    from screen_reader import ScreenReader

    start, midgame = screenshots
    reader = ScreenReader()
    assert reader.learn(start, expected_grid(chess.Board(), chess.BLACK)).errors == 0
    assert (reader.read(midgame) == parse(MIDGAME)).all()
