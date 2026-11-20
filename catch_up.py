"""Catch up with a game that moved on while we were not looking.

When the picture differs from the tracked position by more moves than the quick reader considers (the
opponent answered instantly, the engine was busy, the player played fast), the missing moves are searched
for: from the tracked position, the sequence of legal moves is looked for whose result puts every piece on
the squares seen on the screen. Where pieces stand and in which colour is read reliably; the piece
recogniser only decides between sequences that end the same way (which knight moved)."""

import chess
import numpy as np

from move_inference import square_to_cell

MAX_PLIES = 8


def plausible_successor(before: chess.Board, after: chess.Board) -> bool:
    """Could `after` be a later position of the same game as `before`? Pieces are only ever lost, never gained
    (except by promotion: a pawn turning into another piece). Used to refuse readings of a half-made move."""
    if after.board_fen() == chess.STARTING_BOARD_FEN:
        return True  # a new game
    for colour in (chess.WHITE, chess.BLACK):
        if len(after.pieces(chess.PAWN, colour)) > len(before.pieces(chess.PAWN, colour)):
            return False
        lost_pawns = len(before.pieces(chess.PAWN, colour)) - len(after.pieces(chess.PAWN, colour))
        gained = sum(max(0, len(after.pieces(t, colour)) - len(before.pieces(t, colour))) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
        if gained > lost_pawns:
            return False
        if chess.popcount(after.occupied_co[colour]) > chess.popcount(before.occupied_co[colour]):
            return False
    return True
BEAM = 500
KIND_WEIGHT = 0.3


def bitboards_from_grid(occupied: np.ndarray, white: np.ndarray, user_color: bool) -> tuple[int, int, int]:
    """(white squares, black squares, squares the reader is unsure about) as chess bitboards, from 8x8
    probabilities in image orientation. Unsure squares are left out of the comparison."""
    white_bb = black_bb = unsure = 0
    for square in chess.SQUARES:
        row, col = square_to_cell(square, user_color)
        p_piece, p_white = float(occupied[row, col]), float(white[row, col])
        if 0.15 < p_piece < 0.85 or (p_piece >= 0.5 and 0.15 < p_white < 0.85):
            unsure |= chess.BB_SQUARES[square]
        if occupied[row, col] >= 0.5:
            if white[row, col] >= 0.5:
                white_bb |= chess.BB_SQUARES[square]
            else:
                black_bb |= chess.BB_SQUARES[square]
    return white_bb, black_bb, unsure


def kind_masks(kinds: dict[int, str], colour_of: dict[int, str], user_color: bool) -> dict[tuple[int, bool], int]:
    """{(piece type, colour): bitboard} from the recogniser's reading (image square index -> kind letter)."""
    cell_to_square = {square_to_cell(sq, user_color): sq for sq in chess.SQUARES}
    masks = {(t, c): 0 for t in chess.PIECE_TYPES for c in (chess.WHITE, chess.BLACK)}
    for index, kind in kinds.items():
        square = cell_to_square[divmod(index, 8)]
        masks[(chess.PIECE_SYMBOLS.index(kind), colour_of[index] == "w")] |= chess.BB_SQUARES[square]
    return masks


def _cost(board: chess.Board, white_bb: int, black_bb: int, masks, care: int) -> tuple[int, int]:
    occupancy = ((board.occupied_co[chess.WHITE] ^ white_bb) & care).bit_count() + ((board.occupied_co[chess.BLACK] ^ black_bb) & care).bit_count()
    kinds = 0
    if masks:
        for (piece_type, colour), wanted in masks.items():
            kinds += (board.pieces_mask(piece_type, colour) ^ wanted).bit_count()
    return occupancy, kinds


def _has_shuffle(moves: tuple[chess.Move, ...]) -> bool:
    """Does a piece leave a square and end up back on it? Real play that was missed does not do that; a path
    that needs it is padding made up to explain a picture that is not a position (a piece in mid-drag)."""
    origin: dict[int, int] = {}
    for move in moves:
        start = origin.pop(move.from_square, move.from_square)
        origin[move.to_square] = start
    return any(now == start for now, start in origin.items() if now in {m.to_square for m in moves})


def find_moves(board: chess.Board, white_bb: int, black_bb: int, masks=None, unsure: int = 0, max_plies: int = MAX_PLIES, beam: int = BEAM) -> list[chess.Move] | None:
    """The shortest legal sequence from `board` that leaves White on `white_bb` and Black on `black_bb`.
    [] when nothing changed, None when no sequence of at most `max_plies` moves does it."""
    start = board.copy(stack=False)
    care = chess.BB_ALL & ~unsure
    occupancy, _ = _cost(start, white_bb, black_bb, masks, care)
    if occupancy == 0:
        return []
    frontier: list[tuple[chess.Board, tuple[chess.Move, ...]]] = [(start, ())]
    seen = {start._transposition_key()}
    for _ in range(max_plies):
        scored = []
        solutions = []
        for position, moves in frontier:
            for move in position.legal_moves:
                child = position.copy(stack=False)
                child.push(move)
                key = child._transposition_key()
                if key in seen:
                    continue
                seen.add(key)
                occupancy, kinds = _cost(child, white_bb, black_bb, masks, care)
                if occupancy == 0 and not _has_shuffle(moves + (move,)):
                    solutions.append((kinds, moves + (move,)))
                scored.append((occupancy + KIND_WEIGHT * kinds, child, moves + (move,)))
        if solutions:
            return list(min(solutions, key=lambda item: item[0])[1])
        scored.sort(key=lambda item: item[0])
        frontier = [(child, moves) for _, child, moves in scored[:beam]]
        if not frontier:
            return None
    return None
