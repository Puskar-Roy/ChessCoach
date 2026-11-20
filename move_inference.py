"""Infer which move was played by comparing what the camera sees to every legal move.

The camera reading is a coarse 8x8 grid (empty / white / black). Each legal move predicts a grid;
the move whose prediction best matches wins, but only if it clearly beats the runner-up. Legality
from python-chess is what makes this robust to a few misread squares."""

from dataclasses import dataclass

import chess
import numpy as np

from board_reader import BLACK, EMPTY, WHITE


def square_to_cell(square: int, user_color: bool) -> tuple[int, int]:
    """(row, col) in the warped image. The user's side of the board is at the bottom."""
    file, rank = chess.square_file(square), chess.square_rank(square)
    if user_color == chess.WHITE:
        return 7 - rank, file
    return rank, 7 - file


def expected_grid(board: chess.Board, user_color: bool) -> np.ndarray:
    grid = np.zeros((8, 8), dtype=np.int8)
    for square, piece in board.piece_map().items():
        row, col = square_to_cell(square, user_color)
        grid[row, col] = WHITE if piece.color == chess.WHITE else BLACK
    return grid


@dataclass(frozen=True)
class Inference:
    status: str  # "move" | "unchanged" | "ambiguous"
    move: chess.Move | None
    errors: int  # mismatched squares for the best candidate
    runner_up: int  # mismatched squares for the second best distinct candidate
    mismatches: tuple[str, ...] = ()  # squares where the best candidate and the camera disagree


def infer_move(
    board: chess.Board,
    observed: np.ndarray,
    user_color: bool,
    max_errors: int = 2,
    margin: int = 2,
) -> Inference:
    work = board.copy(stack=False)
    candidates: dict[bytes, tuple[int, chess.Move | None, np.ndarray]] = {}

    base = expected_grid(work, user_color)
    candidates[base.tobytes()] = (int((base != observed).sum()), None, base)

    moves = sorted(work.legal_moves, key=lambda m: 0 if m.promotion in (None, chess.QUEEN) else 1)
    for move in moves:
        work.push(move)
        grid = expected_grid(work, user_color)
        work.pop()
        key = grid.tobytes()
        if key not in candidates:  # promotions to other pieces look identical; queen wins
            candidates[key] = (int((grid != observed).sum()), move, grid)

    ranked = sorted(candidates.values(), key=lambda item: item[0])
    best_errors, best_move, best_grid = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 99

    bad_cells = np.argwhere(best_grid != observed)
    mismatches = tuple(_cell_name(r, c, user_color) for r, c in bad_cells)

    if best_errors > max_errors or runner_up - best_errors < margin:
        status = "ambiguous"
    elif best_move is None:
        status = "unchanged"
    else:
        status = "move"
    return Inference(status, best_move, best_errors, runner_up, mismatches)


def infer_moves(
    board: chess.Board,
    observed: np.ndarray,
    user_color: bool,
    max_moves: int = 2,
) -> tuple[list[chess.Move], Inference]:
    """Infer the move(s) played since `board`. Usually one; a second is tried when the first
    leaves mismatches (e.g. both players moved before the picture was stable).

    Returns (moves, first_inference). `moves` is empty unless the first inference was a move."""
    first = infer_move(board, observed, user_color)
    if first.status != "move":
        return [], first
    work = board.copy(stack=False)
    moves = [first.move]
    work.push(first.move)
    last = first
    while last.errors > 0 and len(moves) < max_moves:
        last = infer_move(work, observed, user_color)
        if last.status != "move":
            break
        moves.append(last.move)
        work.push(last.move)
    return moves, first


def _cell_name(row: int, col: int, user_color: bool) -> str:
    if user_color == chess.WHITE:
        return chess.square_name(chess.square(col, 7 - row))
    return chess.square_name(chess.square(7 - col, row))
