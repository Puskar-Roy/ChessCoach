"""Work out which move(s) were played from per-square probabilities, using the rules of chess.

The reader says, for each square, how likely it holds a piece and how likely that piece is white. Every
legal move (and every pair or triple of moves, when the opponent answered before we looked) predicts a
board; we score each prediction by the log-likelihood of the picture under it and pick the best. Because
the score is probabilistic, a square the reader is unsure about barely matters, while a confident square
counts a lot - far more reliable than counting hard mismatches.

A result is only returned when it clearly beats the runner-up (margin) and explains the picture well
(regret); otherwise the caller is told the picture is unclear and nothing is guessed."""

from dataclasses import dataclass

import chess
import numpy as np

from board_reader import BLACK, EMPTY, WHITE
from move_inference import _cell_name, expected_grid

EPS = 1e-3
MARGIN = 4.0  # nats: the best explanation must beat the next one by this much
MAX_REGRET = 9.0  # nats: how far the best explanation may fall short of a perfect match
EXPLAINED = 3.0  # nats: close enough to perfect that a single move is accepted without looking deeper
PLY_PENALTY = 1.5  # explaining the picture with more moves needs more evidence


@dataclass(frozen=True)
class Reading:
    status: str  # "move" | "unchanged" | "unclear"
    moves: tuple[chess.Move, ...] = ()
    margin: float = 0.0
    regret: float = 0.0
    doubtful: tuple[str, ...] = ()  # squares that disagree with the best explanation


def loglik_tables(occupied: np.ndarray, white: np.ndarray) -> np.ndarray:
    occupied = np.clip(occupied, EPS, 1 - EPS)
    white = np.clip(white, EPS, 1 - EPS)
    table = np.zeros((3, 8, 8))
    table[EMPTY] = np.log(1 - occupied)
    table[WHITE] = np.log(occupied) + np.log(white)
    table[BLACK] = np.log(occupied) + np.log(1 - white)
    return table


def _score(grid: np.ndarray, table: np.ndarray) -> float:
    return float(table[grid, np.arange(8)[:, None], np.arange(8)[None, :]].sum())


def read_move(
    board: chess.Board,
    occupied: np.ndarray,
    white: np.ndarray,
    user_color: bool,
    max_plies: int = 3,
) -> Reading:
    """`occupied`/`white` are 8x8 probabilities in image orientation (the user's side at the bottom)."""
    table = loglik_tables(occupied, white)
    ideal = float(table.max(axis=0).sum())

    best_per_grid: dict[bytes, tuple[float, tuple[chess.Move, ...], np.ndarray]] = {}

    def consider(moves: tuple[chess.Move, ...], grid: np.ndarray) -> None:
        score = _score(grid, table) - PLY_PENALTY * max(0, len(moves) - 1) - 0.01 * len(moves)
        key = grid.tobytes()
        known = best_per_grid.get(key)
        if known is None or len(moves) < len(known[1]):
            best_per_grid[key] = (score, moves, grid)

    work = board.copy(stack=False)
    consider((), expected_grid(work, user_color))
    frontier = [((), work)]
    reached = 0
    for depth in range(1, max_plies + 1):
        nxt = []
        for moves, position in frontier:
            ordered = sorted(position.legal_moves, key=lambda m: 0 if m.promotion in (None, chess.QUEEN) else 1)
            for move in ordered:
                child = position.copy(stack=False)
                child.push(move)
                grid = expected_grid(child, user_color)
                consider(moves + (move,), grid)
                nxt.append((moves + (move,), child))
        frontier = nxt
        reached = depth
        ranked = sorted(best_per_grid.values(), key=lambda item: -item[0])
        gap, shortfall = ranked[0][0] - ranked[1][0], ideal - ranked[0][0]
        if depth == 1 and gap >= MARGIN and shortfall <= EXPLAINED:
            break  # one move explains the picture almost perfectly: no need to consider more
        clear = gap >= MARGIN and shortfall <= MAX_REGRET
        if depth >= 2 and (clear or shortfall > 2 * MAX_REGRET):
            break  # clear already, or the picture is too far off for a third move to explain it (keeps this fast)
        if depth >= max_plies:
            break
    ranked = sorted(best_per_grid.values(), key=lambda item: -item[0])
    best, runner = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    margin = best[0] - runner[0] if runner else 99.0
    regret = ideal - best[0]
    mismatch = np.argwhere(best[2] != np.where(occupied < 0.5, EMPTY, np.where(white >= 0.5, WHITE, BLACK)))
    doubtful = tuple(_cell_name(int(r), int(c), user_color) for r, c in mismatch[:6])
    if margin < MARGIN or regret > MAX_REGRET:
        return Reading("unclear", margin=margin, regret=regret, doubtful=doubtful)
    if not best[1]:
        return Reading("unchanged", margin=margin, regret=regret)
    return Reading("move", best[1], margin, regret, doubtful)
