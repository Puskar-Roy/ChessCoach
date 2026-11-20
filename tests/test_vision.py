import random

import chess
import cv2
import numpy as np
import pytest

from board_reader import BLACK, EMPTY, WHITE, BoardReader, grid_to_text
from calibration import Calibration, order_corners
from move_inference import expected_grid, infer_move, infer_moves, square_to_cell
from synth import FRAME_CORNERS, render_frame, render_topdown


def make_pipeline(user_color):
    calibration = Calibration(FRAME_CORNERS)
    reader = BoardReader()
    board = chess.Board()
    warped = calibration.warp(render_frame(board, user_color, seed=1))
    report = reader.learn(warped, expected_grid(board, user_color))
    return calibration, reader, report


def test_order_corners_any_input_order():
    corners = [[500, 400], [100, 60], [60, 410], [520, 70]]
    ordered = order_corners(corners)
    assert ordered[0].tolist() == [100, 60]
    assert ordered[1].tolist() == [520, 70]
    assert ordered[2].tolist() == [500, 400]
    assert ordered[3].tolist() == [60, 410]


def test_order_corners_rejects_bad_input():
    with pytest.raises(ValueError):
        order_corners([[0, 0], [1, 1], [2, 2]])
    with pytest.raises(ValueError):
        order_corners([[0, 0], [0, 0], [1, 1], [2, 2]])


def test_warp_recovers_topdown_view():
    board = chess.Board()
    calibration = Calibration(FRAME_CORNERS)
    warped = calibration.warp(render_frame(board, chess.WHITE, noise=0))
    reference = render_topdown(board, chess.WHITE)
    # colours are shifted by the lighting gradient, so compare structure loosely
    diff = np.abs(warped.astype(int) - reference.astype(int)).mean()
    assert diff < 35


def test_square_to_cell_orientation():
    assert square_to_cell(chess.A1, chess.WHITE) == (7, 0)
    assert square_to_cell(chess.H8, chess.WHITE) == (0, 7)
    assert square_to_cell(chess.A1, chess.BLACK) == (0, 7)
    assert square_to_cell(chess.H8, chess.BLACK) == (7, 0)


@pytest.mark.parametrize("user_color", [chess.WHITE, chess.BLACK])
def test_reader_learns_start_position(user_color):
    _, reader, report = make_pipeline(user_color)
    assert report.errors == 0
    assert report.occupied == 32 and report.empty == 32


@pytest.mark.parametrize("user_color", [chess.WHITE, chess.BLACK])
def test_reader_reads_whole_game(user_color):
    calibration, reader, _ = make_pipeline(user_color)
    rng = random.Random(7)
    board = chess.Board()
    worst = 0
    for ply in range(70):
        if board.is_game_over():
            break
        board.push(rng.choice(list(board.legal_moves)))
        warped = calibration.warp(render_frame(board, user_color, seed=ply))
        errors = int((reader.read(warped) != expected_grid(board, user_color)).sum())
        worst = max(worst, errors)
    assert worst <= 2


@pytest.mark.parametrize("user_color", [chess.WHITE, chess.BLACK])
def test_infers_every_move_of_a_game(user_color):
    calibration, reader, _ = make_pipeline(user_color)
    rng = random.Random(11)
    board = chess.Board()
    played = 0
    for ply in range(80):
        if board.is_game_over():
            break
        move = rng.choice(list(board.legal_moves))
        after = board.copy()
        after.push(move)
        warped = calibration.warp(render_frame(after, user_color, seed=100 + ply))
        result = infer_move(board, reader.read(warped), user_color)
        assert result.status == "move", (ply, board.fen(), move, result)
        expected_promo = move.promotion in (None, chess.QUEEN)
        if expected_promo:
            assert result.move == move
        board = after
        played += 1
    assert played >= 30


def test_unchanged_board_detected():
    calibration, reader, _ = make_pipeline(chess.WHITE)
    board = chess.Board()
    board.push_san("e4")
    warped = calibration.warp(render_frame(board, chess.WHITE, seed=3))
    result = infer_move(board, reader.read(warped), chess.WHITE)
    assert result.status == "unchanged"


def test_castling_en_passant_and_promotion():
    cases = [
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "O-O"),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "O-O-O"),
        ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "exd6"),
        ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a8=Q+"),
    ]
    for fen, san in cases:
        board = chess.Board(fen)
        move = board.parse_san(san)
        observed = _grid_after(board, move, chess.WHITE)
        result = infer_move(board, observed, chess.WHITE)
        assert result.status == "move" and result.move == move, san


def _grid_after(board, move, user_color):
    after = board.copy()
    after.push(move)
    return expected_grid(after, user_color)


def test_tolerates_one_misread_square():
    board = chess.Board()
    move = board.parse_san("Nf3")
    observed = _grid_after(board, move, chess.WHITE).copy()
    observed[3, 3] = BLACK  # phantom piece in the middle
    result = infer_move(board, observed, chess.WHITE)
    assert result.status == "move" and result.move == move
    assert result.errors == 1


def test_garbage_reading_is_ambiguous():
    board = chess.Board()
    observed = expected_grid(board, chess.WHITE).copy()
    observed[2:6, :] = BLACK
    assert infer_move(board, observed, chess.WHITE).status == "ambiguous"


def test_two_moves_before_stable_are_both_found():
    board = chess.Board()
    after = board.copy()
    after.push_san("e4")
    after.push_san("e5")
    moves, _ = infer_moves(board, expected_grid(after, chess.WHITE), chess.WHITE)
    assert [board.san(moves[0])] == ["e4"]
    assert [m.uci() for m in moves] == ["e2e4", "e7e5"]


def test_three_moves_ahead_is_not_guessed():
    board = chess.Board()
    after = board.copy()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4"]:
        after.push_san(san)
    moves, first = infer_moves(board, expected_grid(after, chess.WHITE), chess.WHITE)
    assert moves == [] and first.status == "ambiguous"


def test_single_move_returns_one():
    board = chess.Board()
    move = board.parse_san("d4")
    moves, _ = infer_moves(board, _grid_after(board, move, chess.WHITE), chess.WHITE)
    assert moves == [move]


def test_grid_text():
    grid = np.zeros((8, 8), dtype=np.int8)
    grid[0, 0], grid[7, 7] = BLACK, WHITE
    lines = grid_to_text(grid).splitlines()
    assert lines[0].startswith("b") and lines[7].endswith("W")


def test_clicks_in_player_order_work_for_any_camera_rotation():
    board = chess.Board()
    board.push_san("e4")
    frame = render_frame(board, chess.WHITE, seed=5, noise=0)
    tl, tr, br, bl = FRAME_CORNERS
    reference = Calibration.from_clicks([bl, br, tr, tl]).warp(frame)

    rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    height = frame.shape[0]

    def rotate_point(p):  # (x, y) -> clockwise 90 degree rotation
        return (height - 1 - p[1], p[0])

    clicks = [rotate_point(p) for p in (bl, br, tr, tl)]  # still the user's bottom-left first
    warped = Calibration.from_clicks(clicks).warp(rotated)
    assert np.abs(warped.astype(int) - reference.astype(int)).mean() < 3


def test_calibration_save_load_roundtrip(tmp_path):
    original = Calibration.from_clicks([(10, 400), (500, 410), (480, 30), (40, 20)])
    path = tmp_path / "cal.json"
    original.save(path)
    loaded = Calibration.load(path)
    assert np.allclose(original.corners, loaded.corners)
    assert np.allclose(original.matrix, loaded.matrix)


def test_exposure_drift_is_handled_with_empty_hint():
    calibration, reader, _ = make_pipeline(chess.WHITE)
    rng = random.Random(3)
    board = chess.Board()
    errors_with_hint = 0
    for ply in range(40):
        if board.is_game_over():
            break
        previous = board.copy()
        board.push(rng.choice(list(board.legal_moves)))
        frame = render_frame(board, chess.WHITE, seed=ply).astype(np.float32)
        frame = np.clip(frame * 1.15 + 6, 0, 255).astype(np.uint8)  # camera auto-exposure drift
        warped = calibration.warp(frame)
        hint = expected_grid(previous, chess.WHITE) == EMPTY
        observed = reader.read(warped, empty_hint=hint)
        errors_with_hint += int((observed != expected_grid(board, chess.WHITE)).sum())
        moves, _ = infer_moves(previous, observed, chess.WHITE)
        assert moves and moves[0] == board.peek()
    assert errors_with_hint <= 10
