"""Boards shown on screen: last-move highlights and legal-move dots must not fool the reader."""

import random

import chess
import pytest

from board_reader import BoardReader
from move_inference import expected_grid, infer_move
from synth import render_topdown


@pytest.mark.parametrize("user_color", [chess.WHITE, chess.BLACK])
def test_every_move_is_found_with_highlights_and_dots(user_color):
    start = chess.Board()
    reader = BoardReader(augment=True)
    report = reader.learn(render_topdown(start, user_color), expected_grid(start, user_color))
    assert report.errors <= 1

    rng = random.Random(5)
    board = chess.Board()
    for ply in range(60):
        if board.is_game_over():
            break
        move = rng.choice(list(board.legal_moves))
        after = board.copy()
        after.push(move)
        dots = [m.to_square for m in rng.sample(list(after.legal_moves), min(5, after.legal_moves.count()))]
        dots = [sq for sq in dots if after.piece_at(sq) is None]
        image = render_topdown(after, user_color, highlights=[move.from_square, move.to_square], dots=dots)
        result = infer_move(board, reader.read(image), user_color)
        assert result.status == "move", (ply, board.fen(), move, result)
        if move.promotion in (None, chess.QUEEN):
            assert result.move == move
        board = after


def test_flipped_board_is_reported_instead_of_learned_wrong():
    start = chess.Board()
    seen_from_black = render_topdown(start, chess.BLACK)
    with pytest.raises(ValueError, match="flipped"):
        BoardReader(augment=True).learn(seen_from_black, expected_grid(start, chess.WHITE))


def test_find_board_snaps_a_sloppy_rectangle_to_the_grid():
    import cv2
    import numpy as np
    from screen_capture import find_board

    board = render_topdown(chess.Board(), chess.WHITE)  # 480x480, squares of 60 px
    screen = np.full((900, 1200, 3), (40, 36, 34), np.uint8)
    screen[150:630, 300:780] = board  # the board sits at x=300, y=150
    for rect in [(300, 150, 480, 480), (330, 190, 420, 430), (270, 120, 560, 560), (300, 210, 480, 420)]:
        x, y, size = find_board(screen, rect)
        assert abs(x - 300) <= 2 and abs(y - 150) <= 2 and abs(size - 480) <= 4, (rect, x, y, size)


def test_corner_picker_text_is_not_drawn_over_the_board(monkeypatch):
    import cv2
    import numpy as np
    import calibration

    snapshot = np.full((300, 400, 3), 200, np.uint8)
    shown = []
    callbacks = {}
    keys = iter([-1, -1, -1, -1, 13])

    monkeypatch.setattr(cv2, "setMouseCallback", lambda name, fn: callbacks.update(fn=fn))
    monkeypatch.setattr(cv2, "imshow", lambda name, image: shown.append(image))
    monkeypatch.setattr(cv2, "getWindowProperty", lambda *a: 1.0)

    def fake_wait(delay):
        # click the four corners, one per frame, in the picture's own coordinates + the header height
        if len(shown) <= 4:
            header = shown[-1].shape[0] - snapshot.shape[0]
            x, y = [(20, 280), (380, 280), (380, 20), (20, 20)][len(shown) - 1]
            callbacks["fn"](cv2.EVENT_LBUTTONDOWN, x, y + header, 0, None)
            return -1
        return 13

    monkeypatch.setattr(cv2, "waitKey", fake_wait)
    clicks = calibration.pick_corners(snapshot, chess.WHITE)
    assert clicks == [(20, 280), (380, 280), (380, 20), (20, 20)]
    # the picture itself is untouched below the instruction strip
    assert (shown[-1][-snapshot.shape[0]:][60:240, 60:340] == 200).all()
