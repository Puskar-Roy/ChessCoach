"""Simple tactical motif detection (forks, pins, skewers, hanging pieces, discovered attacks)
built on python-chess attack maps rather than raw engine evaluation."""

from dataclasses import dataclass

import chess

VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}
NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
SLIDER_DIRS = {
    chess.ROOK: ROOK_DIRS,
    chess.BISHOP: BISHOP_DIRS,
    chess.QUEEN: ROOK_DIRS + BISHOP_DIRS,
}


@dataclass(frozen=True)
class Motif:
    kind: str  # fork | pin | skewer | discovered | hanging
    text: str  # verb phrase, e.g. "forks the rook on a8 and the king on e8"
    move: chess.Move | None = None
    squares: tuple[int, ...] = ()


def describe(board: chess.Board, square: int) -> str:
    piece = board.piece_at(square)
    name = NAMES[piece.piece_type] if piece else "piece"
    return f"{name} on {chess.square_name(square)}"


def _value_at(board: chess.Board, square: int) -> int:
    return VALUES[board.piece_type_at(square)]


def _as_turn(board: chess.Board, color: bool) -> chess.Board | None:
    """A copy of the board where it is `color`'s turn (passing with a null move if needed)."""
    if board.turn == color:
        return board
    other = board.copy(stack=False)
    if other.is_check():
        return None
    other.push(chess.Move.null())
    return other


def hanging_pieces(board: chess.Board, color: bool) -> list[int]:
    """Squares of `color`'s pieces that can be captured for free or for a profit."""
    out = []
    for square in chess.SquareSet(board.occupied_co[color]):
        piece_type = board.piece_type_at(square)
        if piece_type == chess.KING:
            continue
        attackers = board.attackers(not color, square)
        if not attackers:
            continue
        if not board.attackers(color, square):
            out.append(square)
            continue
        cheapest = min(_value_at(board, a) for a in attackers)
        if cheapest < VALUES[piece_type]:
            out.append(square)
    out.sort(key=lambda s: -_value_at(board, s))
    return out


def _ray_pairs(board: chess.Board, square: int, directions):
    """For each direction, yield the first two pieces met along the ray."""
    for d_file, d_rank in directions:
        file, rank = chess.square_file(square) + d_file, chess.square_rank(square) + d_rank
        first = None
        while 0 <= file < 8 and 0 <= rank < 8:
            target = chess.square(file, rank)
            if board.piece_at(target):
                if first is None:
                    first = target
                else:
                    yield first, target
                    break
            file += d_file
            rank += d_rank


def pins_and_skewers(board: chess.Board, color: bool) -> list[Motif]:
    """Pins and skewers that `color`'s sliding pieces are creating against the opponent."""
    out = []
    for square in chess.SquareSet(board.occupied_co[color]):
        piece_type = board.piece_type_at(square)
        directions = SLIDER_DIRS.get(piece_type)
        if not directions:
            continue
        for first, second in _ray_pairs(board, square, directions):
            if board.color_at(first) == color or board.color_at(second) == color:
                continue
            v1, v2 = _value_at(board, first), _value_at(board, second)
            if v2 > v1 and (board.piece_type_at(second) == chess.KING or (v1 >= 3 and v2 >= v1 + 2)):
                out.append(
                    Motif(
                        "pin",
                        f"pins the {describe(board, first)} to the {describe(board, second)}",
                        squares=(square, first, second),
                    )
                )
            elif v1 > v2 and v1 >= 5 and v2 >= 3:
                out.append(
                    Motif(
                        "skewer",
                        f"skewers the {describe(board, first)} against the {describe(board, second)}",
                        squares=(square, first, second),
                    )
                )
    return out


def _is_safe(after: chess.Board, square: int, color: bool) -> bool:
    attackers = after.attackers(not color, square)
    if not attackers:
        return True
    if not after.attackers(color, square):
        return False
    mover_value = _value_at(after, square)
    return min(_value_at(after, a) for a in attackers) >= mover_value


def _fork_after(after: chess.Board, move: chess.Move, color: bool) -> Motif | None:
    to_square = move.to_square
    mover_value = _value_at(after, to_square)
    targets = []
    for target in chess.SquareSet(after.attacks(to_square) & after.occupied_co[not color]):
        piece_type = after.piece_type_at(target)
        if piece_type == chess.KING:
            targets.append(target)
            continue
        value = VALUES[piece_type]
        if value < 3:
            continue
        if value > mover_value or not after.attackers(not color, target):
            targets.append(target)
    if len(targets) < 2 or not _is_safe(after, to_square, color):
        return None
    targets.sort(key=lambda s: -_value_at(after, s))
    first, second = targets[0], targets[1]
    return Motif(
        "fork",
        f"forks the {describe(after, first)} and the {describe(after, second)}",
        move=move,
        squares=(to_square, first, second),
    )


def _discovered_after(board: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Motif | None:
    enemy = not color
    best = None
    for target in chess.SquareSet(after.occupied_co[enemy]):
        if target == move.to_square:
            continue
        piece_type = after.piece_type_at(target)
        if piece_type != chess.KING and VALUES[piece_type] < 5:
            continue
        before_attackers = set(board.attackers(color, target)) - {move.from_square}
        after_attackers = set(after.attackers(color, target)) - {move.to_square}
        if after_attackers - before_attackers:
            candidate = (VALUES[piece_type], target)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    target = best[1]
    if after.is_check() and after.king(enemy) == target:
        text = f"uncovers a check on the king on {chess.square_name(target)}"
    else:
        text = f"uncovers an attack on the {describe(after, target)}"
    return Motif("discovered", text, move=move, squares=(target,))


def motifs_for_move(board: chess.Board, move: chess.Move) -> list[Motif]:
    """Tactical ideas created by playing `move` (board is the position before the move)."""
    color = board.turn
    after = board.copy(stack=False)
    after.push(move)
    out = []
    fork = _fork_after(after, move, color)
    if fork:
        out.append(fork)
    discovered = _discovered_after(board, after, move, color)
    if discovered:
        out.append(discovered)
    before_keys = {(m.kind, m.squares[1:]) for m in pins_and_skewers(board, color)}
    for motif in pins_and_skewers(after, color):
        if (motif.kind, motif.squares[1:]) not in before_keys:
            out.append(Motif(motif.kind, motif.text, move=move, squares=motif.squares))
    return out


def forks(board: chess.Board, color: bool) -> list[Motif]:
    """Every fork `color` could play on their next move."""
    base = _as_turn(board, color)
    if base is None:
        return []
    out = []
    for move in base.legal_moves:
        after = base.copy(stack=False)
        after.push(move)
        fork = _fork_after(after, move, color)
        if fork:
            out.append(fork)
    return out


def fork_threats(board: chess.Board, victim: bool) -> list[tuple[str, Motif]]:
    """Forks the opponent of `victim` threatens; returns (san, motif) pairs."""
    attacker = not victim
    base = _as_turn(board, attacker)
    if base is None:
        return []
    out = []
    for motif in forks(board, attacker):
        out.append((base.san(motif.move), motif))
    return out


def discovered_attacks(board: chess.Board, color: bool) -> list[Motif]:
    base = _as_turn(board, color)
    if base is None:
        return []
    out = []
    for move in base.legal_moves:
        after = base.copy(stack=False)
        after.push(move)
        motif = _discovered_after(base, after, move, color)
        if motif:
            out.append(motif)
    return out


def pinned_pieces(board: chess.Board, color: bool) -> list[int]:
    """Squares of `color`'s pieces that are absolutely pinned to their own king."""
    return [
        square
        for square in chess.SquareSet(board.occupied_co[color])
        if board.piece_type_at(square) != chess.KING and board.is_pinned(color, square)
    ]
