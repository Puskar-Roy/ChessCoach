import chess
import numpy as np

from board_reader import BLACK, WHITE
from move_inference import expected_grid
from vision_infer import read_move


def probabilities(board, user_color, confidence=0.97):
    """What a good reader reports for a position: confident everywhere."""
    grid = expected_grid(board, user_color)
    occupied = np.where(grid != 0, confidence, 1 - confidence)
    white = np.where(grid == WHITE, confidence, 1 - confidence)
    return occupied, white


def test_a_single_move_is_read():
    board = chess.Board()
    after = board.copy()
    after.push_san("e4")
    reading = read_move(board, *probabilities(after, chess.WHITE), chess.WHITE)
    assert reading.status == "move" and [m.uci() for m in reading.moves] == ["e2e4"]


def test_no_change_means_unchanged():
    board = chess.Board()
    assert read_move(board, *probabilities(board, chess.BLACK), chess.BLACK).status == "unchanged"


def test_my_move_and_an_instant_reply_are_both_found():
    board = chess.Board()
    after = board.copy()
    for san in ("d4", "d5", "c4"):
        after.push_san(san)
    reading = read_move(board, *probabilities(after, chess.WHITE), chess.WHITE)
    assert reading.status == "move" and [m.uci() for m in reading.moves] == ["d2d4", "d7d5", "c2c4"]


def test_castling_and_en_passant_are_understood():
    board = chess.Board("r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1")
    for san in ("O-O", "exd6", "O-O-O"):
        after = board.copy()
        after.push_san(san)
        reading = read_move(board, *probabilities(after, chess.WHITE), chess.WHITE)
        assert reading.status == "move" and reading.moves[0] == board.parse_san(san), san


def test_a_few_uncertain_squares_do_not_matter():
    board = chess.Board()
    after = board.copy()
    after.push_san("Nf3")
    occupied, white = probabilities(after, chess.WHITE)
    for row, col in ((0, 0), (3, 4), (6, 6)):  # the reader shrugs at three squares
        occupied[row, col] = 0.5
        white[row, col] = 0.5
    reading = read_move(board, occupied, white, chess.WHITE)
    assert reading.status == "move" and reading.moves[0].uci() == "g1f3"


def test_garbage_is_reported_unclear_instead_of_guessed():
    rng = np.random.default_rng(1)
    reading = read_move(chess.Board(), rng.uniform(0.02, 0.98, (8, 8)), rng.uniform(0.02, 0.98, (8, 8)), chess.WHITE)
    assert reading.status == "unclear"


def test_black_at_the_bottom_works_too():
    board = chess.Board()
    board.push_san("e4")
    after = board.copy()
    after.push_san("c5")
    reading = read_move(board, *probabilities(after, chess.BLACK), chess.BLACK)
    assert reading.status == "move" and reading.moves[0].uci() == "c7c5"
