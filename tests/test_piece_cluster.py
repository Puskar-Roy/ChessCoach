import chess
import cv2
import numpy as np
import pytest

import sitegen
from move_inference import square_to_cell
from piece_classifier import MODEL_PATH
from piece_cluster import analyse_position, placement_to_fen


def mid_game(rng, plies):
    board = chess.Board()
    for _ in range(plies):
        if board.is_game_over():
            break
        board.push(rng.choice(list(board.legal_moves)))
    return board


def test_colours_are_always_right_and_look_alike_groups_never_mix_piece_kinds():
    rng = np.random.default_rng(4)
    squares = wrong_colour = groups_total = impure = 0
    for i, (theme, style) in enumerate([("green", "classic"), ("brown", "neo"), ("blue", "wood"), ("purple", "classic"), ("gray", "neo")] * 2):
        user = chess.WHITE if i % 2 else chess.BLACK
        board = mid_game(rng, int(rng.integers(12, 60)))
        image = sitegen.render_board(board, user, 70, theme, style, last_move=board.peek() if board.move_stack else None, rng=rng)
        result = analyse_position(cv2.resize(image, (480, 480), interpolation=cv2.INTER_AREA))
        assert result["ok"]
        truth = {}
        for square, piece in board.piece_map().items():
            row, col = square_to_cell(square, user)
            truth[row * 8 + col] = piece
        assert sum(len(g["squares"]) for g in result["groups"]) == len(truth), "every piece must belong to a group"
        for group in result["groups"]:
            kinds = {(truth[s].piece_type, truth[s].color) for s in group["squares"]}
            groups_total += 1
            impure += len(kinds) > 1
            for s in group["squares"]:
                squares += 1
                wrong_colour += (truth[s].color == chess.WHITE) != (group["color"] == "w")
    assert wrong_colour == 0
    assert impure / groups_total <= 0.06, f"{impure} of {groups_total} groups mix different pieces"


def test_a_picture_without_pieces_is_refused():
    empty = sitegen.render_board(chess.Board("8/8/8/8/8/8/8/8 w - - 0 1"), chess.WHITE, 60, "green", "classic")
    assert not analyse_position(cv2.resize(empty, (480, 480)))["ok"]


def test_fen_is_built_for_either_side_at_the_bottom():
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")
    for user in (chess.WHITE, chess.BLACK):
        cells = {}
        for square, piece in board.piece_map().items():
            row, col = square_to_cell(square, user)
            cells[row * 8 + col] = piece.symbol()
        fen = placement_to_fen(cells, "w" if user == chess.WHITE else "b", "w", "KQkq")
        assert fen.split()[0] == board.board_fen()


def test_side_to_move_is_read_from_the_last_move_highlight():
    rng = np.random.default_rng(12)
    right = wrong = unknown = 0
    for i in range(30):
        user = chess.WHITE if i % 2 else chess.BLACK
        board = mid_game(rng, int(rng.integers(10, 60)))
        if not board.move_stack or board.is_game_over():
            continue
        theme = ("green", "brown", "blue", "purple")[i % 4]
        image = sitegen.render_board(board, user, 64, theme, "classic", last_move=board.peek(), highlight=("yellow", "lime")[i % 2], rng=rng)
        result = analyse_position(cv2.resize(image, (480, 480), interpolation=cv2.INTER_AREA))
        expected = "w" if board.turn == chess.WHITE else "b"
        if result["turn"] is None:
            unknown += 1
        elif result["turn"] == expected:
            right += 1
        else:
            wrong += 1
    assert wrong <= 2, f"{wrong} wrong guesses"
    assert right >= 20, f"only {right} right, {unknown} unknown"


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="optional piece-recognition model is not installed")
def test_a_game_under_way_is_read_without_any_help():
    """Pieces, the side at the bottom and whose move it is come from the picture alone."""
    from piece_cluster import read_position

    rng = np.random.default_rng(3)
    exact = turn_ok = checked = 0
    for i in range(12):
        board = mid_game(rng, int(rng.integers(10, 60)))
        if board.is_game_over() or not board.move_stack:
            continue
        user = chess.WHITE if i % 2 else chess.BLACK
        style = ("classic", "neo", "wood")[i % 3]
        image = sitegen.render_board(board, user, 70, ("green", "brown", "blue", "purple")[i % 4], style, last_move=board.peek(), rng=rng)
        result = analyse_position(cv2.resize(image, (480, 480), interpolation=cv2.INTER_AREA))
        position = read_position(result)
        checked += 1
        if position is None:
            continue
        got = chess.Board(position["fen"])
        exact += got.board_fen() == board.board_fen() and position["userColor"] == ("white" if user else "black")
        turn_ok += got.turn == board.turn
    assert checked >= 9
    assert exact >= checked - 1, f"only {exact} of {checked} boards read exactly"
    assert turn_ok >= checked - 1
