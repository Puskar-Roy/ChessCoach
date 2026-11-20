"""Join a game that is already under way.

The reader can tell empty / white / black squares, but not which piece is which, and the position of a
game in progress is not known in advance. Pieces of one kind look identical on a website, so we
  1. split the occupied squares into white and black,
  2. group the squares whose picture is the same (one group = one kind of piece, e.g. "white knight"),
  3. guess what each group is from its shape and how many there are,
and hand the result to the user to confirm or correct - one correction fixes every square of that group.
"""

from dataclasses import dataclass

import chess
import cv2
import numpy as np

from calibration import SQUARE_SIZE
from piece_classifier import KINDS, classify_squares, split_colour
from screen_reader import cell_features

MASK_SIZE = 24
SAME_SPRITE = 0.24  # blended silhouette + edge distance that still counts as "the same piece"


@dataclass
class Group:
    id: int
    color: str  # "w" | "b"
    squares: list[int]  # row * 8 + col in image orientation
    area: float  # share of the square the piece covers
    height: float  # piece height / square size
    symmetry: float  # 1 = mirror-symmetric
    top_width: float  # width of the piece's top quarter relative to its middle
    guess: str = "?"  # one of "pnbrqk" or "?"


def _silhouette(cell_lab: np.ndarray):
    """Foreground mask of one square: pixels that differ from the square's own background ring."""
    s = cell_lab.shape[0]
    inner, outer = int(s * 0.05), max(int(s * 0.13), int(s * 0.05) + 2)
    mid = slice(int(s * 0.3), int(s * 0.7))
    strips = [cell_lab[inner:outer, mid], cell_lab[s - outer : s - inner, mid], cell_lab[mid, inner:outer], cell_lab[mid, s - outer : s - inner]]
    background = np.median(np.concatenate([strip.reshape(-1, 3) for strip in strips]), axis=0)
    distance = np.linalg.norm(cell_lab - background, axis=2)
    mask = (distance > 22).astype(np.uint8)
    margin = int(s * 0.06)
    mask[:margin] = mask[-margin:] = 0
    mask[:, :margin] = mask[:, -margin:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count > 1:  # keep the biggest blob: the piece (drops coordinate letters, dots, rings)
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (labels == biggest).astype(np.uint8)
    return mask


def _filled(mask: np.ndarray) -> np.ndarray:
    """The silhouette with its holes filled: a pale piece on a pale square only shows as an outline."""
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(mask)
    cv2.drawContours(out, contours, -1, 1, -1)
    return out


def _describe(mask: np.ndarray, edges: np.ndarray):
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    # the silhouette keeps its size and position inside the square: a pawn must not look like a bishop
    shape = cv2.resize(mask.astype(np.float32), (MASK_SIZE, MASK_SIZE), interpolation=cv2.INTER_AREA)
    inside = cv2.dilate(mask, np.ones((3, 3), np.uint8))  # the piece's own lines, not the square's or a neighbour's
    detail = cv2.resize(cv2.dilate(edges * inside, np.ones((2, 2), np.uint8)).astype(np.float32), (MASK_SIZE, MASK_SIZE), interpolation=cv2.INTER_AREA)
    crop = mask[y0:y1, x0:x1].astype(np.float32)
    normalized = cv2.resize(crop, (MASK_SIZE, MASK_SIZE), interpolation=cv2.INTER_AREA)
    symmetry = 1.0 - float(np.abs(normalized - normalized[:, ::-1]).mean() / max(normalized.mean(), 1e-6)) / 2
    widths = crop.sum(axis=1)
    quarter = max(1, len(widths) // 4)
    top = float(widths[:quarter].mean())
    middle = float(widths[len(widths) // 3 : 2 * len(widths) // 3].mean()) or 1.0
    return np.stack([shape, detail]), float(mask.mean()), (y1 - y0) / mask.shape[0], symmetry, top / middle


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    """Soft Jaccard distance of the silhouettes, blended with that of their inner lines."""
    shape = np.abs(a[0] - b[0]).sum() / max(np.maximum(a[0], b[0]).sum(), 1e-6)
    detail = np.abs(a[1] - b[1]).sum() / max(np.maximum(a[1], b[1]).sum(), 1e-6)
    return float(0.65 * shape + 0.35 * detail)


def _ring_background(cell_lab: np.ndarray) -> np.ndarray:
    s = cell_lab.shape[0]
    inner, outer = int(s * 0.05), max(int(s * 0.13), int(s * 0.05) + 2)
    mid = slice(int(s * 0.3), int(s * 0.7))
    strips = [cell_lab[inner:outer, mid], cell_lab[s - outer : s - inner, mid], cell_lab[mid, inner:outer], cell_lab[mid, s - outer : s - inner]]
    return np.median(np.concatenate([strip.reshape(-1, 3) for strip in strips]), axis=0)


def guess_side_to_move(lab: np.ndarray, occupied: np.ndarray, is_white: np.ndarray) -> str | None:
    """Websites tint the two squares of the last move. The piece that stands on a tinted square just moved,
    so the other side is to move. Returns "w", "b" or None when the picture does not say."""
    backgrounds = np.zeros((64, 3), np.float32)
    for index in range(64):
        r, c = divmod(index, 8)
        backgrounds[index] = _ring_background(lab[r * SQUARE_SIZE : (r + 1) * SQUARE_SIZE, c * SQUARE_SIZE : (c + 1) * SQUARE_SIZE])
    parity = np.array([(i // 8 + i % 8) % 2 for i in range(64)])
    baseline = {p: np.median(backgrounds[parity == p], axis=0) for p in (0, 1)}
    deviation = np.array([np.linalg.norm(backgrounds[i] - baseline[parity[i]]) for i in range(64)])
    tinted = [i for i in range(64) if deviation[i] > 14 and occupied[i]]
    if not 1 <= len(tinted) <= 2:
        return None
    movers = {bool(is_white[i]) for i in tinted}
    if len(movers) != 1:
        return None
    return "b" if movers.pop() else "w"


def analyse_position(warped: np.ndarray) -> dict:
    """Occupied squares, their colours and the groups of identical pieces, for a warped board picture."""
    occupancy, colour = cell_features(warped)
    presence = occupancy[:, 0]
    occupied = presence > 0.2
    blurred = cv2.GaussianBlur(warped, (3, 3), 0)
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB).astype(np.float32)
    edge_map = (cv2.Canny(cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY), 40, 110) > 0).astype(np.uint8)
    lightness = colour[:, 0].copy()
    masks = {}
    for index in np.flatnonzero(occupied):
        r, c = divmod(int(index), 8)
        mask = _silhouette(lab[r * SQUARE_SIZE : (r + 1) * SQUARE_SIZE, c * SQUARE_SIZE : (c + 1) * SQUARE_SIZE])
        masks[int(index)] = mask
        body = cv2.erode(_filled(mask), np.ones((5, 5), np.uint8))  # the piece's fill, not its outline or the board around it
        if body.sum() < 25:
            body = mask
        if body.sum() >= 25:
            lightness[index] = float(np.median(lab[r * SQUARE_SIZE : (r + 1) * SQUARE_SIZE, c * SQUARE_SIZE : (c + 1) * SQUARE_SIZE, 0][body > 0])) / 100
    probabilities = classify_squares(warped, [int(i) for i in np.flatnonzero(occupied)])
    # two-means on the piece-body lightness: the lighter pile is White (used when there is no trained model)
    values = lightness[occupied]
    if len(values) < 2:
        return {"ok": False, "message": "I can't see any pieces on that board."}
    low, high = float(values.min()), float(values.max())
    for _ in range(12):
        threshold = (low + high) / 2
        a, b = values[values <= threshold], values[values > threshold]
        if len(a) == 0 or len(b) == 0:
            break
        low, high = float(a.mean()), float(b.mean())
    if high - low < 0.25 and not probabilities:
        return {"ok": False, "message": "I can't tell the white pieces from the black ones."}
    threshold = (low + high) / 2
    # white or black: the network's opinion and how light the piece is, weighed together
    spread = high - low
    white_by_model = {}
    for square, p in probabilities.items():
        chance = min(max(split_colour(p)[0], 0.03), 0.97)
        evidence = float(np.log(chance / (1 - chance)))
        if spread >= 0.25:
            evidence += 8 * (float(lightness[square]) - threshold) / spread
        white_by_model[square] = evidence > 0

    groups: list[Group] = []
    shapes: list[np.ndarray] = []
    owner: dict[int, int] = {}
    for index in np.flatnonzero(occupied):
        r, c = divmod(int(index), 8)
        cell = lab[r * SQUARE_SIZE : (r + 1) * SQUARE_SIZE, c * SQUARE_SIZE : (c + 1) * SQUARE_SIZE]
        described = _describe(_silhouette(cell), edge_map[r * SQUARE_SIZE : (r + 1) * SQUARE_SIZE, c * SQUARE_SIZE : (c + 1) * SQUARE_SIZE])
        if described is None:
            continue
        shape, area, height, symmetry, top = described
        color = "w" if white_by_model.get(int(index), lightness[index] > threshold) else "b"
        best, best_distance = None, SAME_SPRITE
        for group, other in zip(groups, shapes):
            if group.color != color:
                continue
            distance = _distance(shape, other)
            if distance < best_distance:
                best, best_distance = group, distance
        if best is None:
            best = Group(len(groups), color, [], area, height, symmetry, top)
            groups.append(best)
            shapes.append(shape)
        best.squares.append(int(index))
        owner[int(index)] = best.id
    groups, shapes, owner = _merge_across_parities(groups, shapes, owner)
    suggest(groups)
    is_white = np.array([white_by_model.get(i, bool(lightness[i] > threshold)) for i in range(64)])
    turn = guess_side_to_move(lab, occupied, is_white)
    reading = recognise(probabilities, groups)
    if reading is not None:
        for group in groups:  # the group's guess follows the recogniser
            counts = [reading["kinds"].get(square) for square in group.squares if square in reading["kinds"]]
            if counts:
                group.guess = max(set(counts), key=counts.count)
    return {
        "ok": True,
        "turn": turn,
        "reading": reading,
        "groups": [group.__dict__ for group in groups],
        "owner": owner,
        "white_count": sum(len(g.squares) for g in groups if g.color == "w"),
        "black_count": sum(len(g.squares) for g in groups if g.color == "b"),
    }


CAPS = {"p": 8, "n": 10, "b": 10, "r": 10, "q": 9}


def _assign_kinds(squares: list[int], logp: dict[int, np.ndarray]) -> tuple[dict[int, str], int]:
    """Best kind for each square of one colour that still makes a legal army. Returns (kinds, repairs)."""
    if not squares:
        return {}, 0
    table = {s: logp[s].copy() for s in squares}
    for s in squares:
        if s // 8 in (0, 7):
            table[s][KINDS.index("p")] = -1e9  # a pawn never stands on the first or last rank
    king = KINDS.index("k")
    others = [i for i in range(len(KINDS)) if i != king]
    best_other = {s: max(table[s][others]) for s in squares}
    king_square = max(squares, key=lambda s: table[s][king] - best_other[s])
    chosen = {s: (king if s == king_square else max(others, key=lambda i: table[s][i])) for s in squares}
    repairs = sum(1 for s in squares if s != king_square and int(np.argmax(table[s])) == king)
    for kind, cap in CAPS.items():
        index = KINDS.index(kind)
        while sum(1 for v in chosen.values() if v == index) > cap:
            of_kind = [s for s in squares if chosen[s] == index]
            weakest = min(of_kind, key=lambda s: table[s][index] - max(table[s][i] for i in others if i != index))
            chosen[weakest] = max((i for i in others if i != index), key=lambda i: table[weakest][i])
            repairs += 1
    return {s: KINDS[i] for s, i in chosen.items()}, repairs


def recognise(probabilities: dict[int, np.ndarray], groups: list[Group]) -> dict | None:
    """Which piece stands on every occupied square, from the picture alone (None without a trained model)."""
    squares = [s for g in groups for s in g.squares]
    if not probabilities or any(s not in probabilities for s in squares):
        return None
    colour_of = {s: g.color for g in groups for s in g.squares}
    logp = {}
    for s in squares:
        _, if_white, if_black = split_colour(probabilities[s])
        logp[s] = np.log(np.clip(if_white if colour_of[s] == "w" else if_black, 1e-4, 1.0))
    smooth = dict(logp)
    for group in groups:  # squares that look identical are the same kind of piece
        mean = np.mean([logp[s] for s in group.squares], axis=0)
        for s in group.squares:
            smooth[s] = 0.5 * logp[s] + 0.5 * mean
    kinds, repairs = {}, 0
    for color in ("w", "b"):
        mine = [s for g in groups if g.color == color for s in g.squares]
        assigned, fixed = _assign_kinds(mine, smooth)
        kinds.update(assigned)
        repairs += fixed
    confidence = {}
    for s, kind in kinds.items():
        e = np.exp(smooth[s] - smooth[s].max())
        confidence[s] = float(e[KINDS.index(kind)] / e.sum())
    return {"kinds": kinds, "confidence": confidence, "repairs": repairs, "sure": min(confidence.values()) if confidence else 0.0}


PARITY_MERGE = 0.28  # looser limit for the same piece seen once on light squares and once on dark ones


def _merge_across_parities(groups, shapes, owner):
    """The same piece on a light and on a dark square gives slightly different pictures: join such groups."""
    def parities(group):
        return {(s // 8 + s % 8) % 2 for s in group.squares}

    alive = list(range(len(groups)))
    merged = True
    while merged:
        merged = False
        for i in alive:
            for j in alive:
                if i >= j or groups[i].color != groups[j].color:
                    continue
                a, b = parities(groups[i]), parities(groups[j])
                if len(a) == 1 and len(b) == 1 and a != b and _distance(shapes[i], shapes[j]) < PARITY_MERGE:
                    groups[i].squares += groups[j].squares
                    alive.remove(j)
                    merged = True
                    break
            if merged:
                break
    result, mapping = [], {}
    for new_id, old in enumerate(alive):
        group = groups[old]
        group.id = new_id
        mapping[old] = new_id
        result.append(group)
    owner = {square: mapping[old] for old, group in enumerate(groups) if old in mapping for square in group.squares}
    return result, [shapes[i] for i in alive], owner


def suggest(groups: list[Group]) -> None:
    """Fill in `guess` for every group, using only what the pictures and the counts tell us."""
    for color in ("w", "b"):
        mine = [g for g in groups if g.color == color]
        if not mine:
            continue
        pawn = max(mine, key=lambda g: len(g.squares))
        if len(pawn.squares) >= 4 or (len(mine) == 1):
            pawn.guess = "p"
        rest = [g for g in mine if g.guess == "?"]
        tall = sorted(rest, key=lambda g: (-g.height, -g.area))
        singles = [g for g in tall if len(g.squares) == 1]
        # the two largest single pieces are king and queen (the king stands a little taller)
        royals = singles[:2]
        for g in royals:
            g.guess = "k" if g is max(royals, key=lambda x: (x.height, -x.area)) and len(royals) == 2 else "q"
        if len(royals) == 1:
            royals[0].guess = "k"
        for g in [g for g in rest if g.guess == "?"]:
            if g.symmetry < 0.78:
                g.guess = "n"  # a horse's head is lopsided
            elif g.top_width > 0.8:
                g.guess = "r"  # a rook's top is as wide as its body
            elif g.top_width < 0.6:
                g.guess = "b"


def placement_to_fen(cells: dict[int, str], user_color: str, turn: str = "w", castling: str = "-", flipped: bool | None = None) -> str:
    """Build a FEN from {image_index: 'N' or 'n'}; `user_color` is the side shown at the bottom of the picture."""
    flipped = (user_color == "b") if flipped is None else flipped
    rows = []
    for rank_from_top in range(8):
        row, empty = "", 0
        for file in range(8):
            r, c = (7 - rank_from_top, 7 - file) if flipped else (rank_from_top, file)
            symbol = cells.get(r * 8 + c)
            if symbol:
                row += (str(empty) if empty else "") + symbol
                empty = 0
            else:
                empty += 1
        rows.append(row + (str(empty) if empty else ""))
    return "/".join(rows) + f" {turn} {castling} - 0 1"


PROBLEMS = {
    chess.STATUS_NO_WHITE_KING: "White needs exactly one king.", chess.STATUS_NO_BLACK_KING: "Black needs exactly one king.",
    chess.STATUS_TOO_MANY_KINGS: "There can only be one king per side.", chess.STATUS_TOO_MANY_WHITE_PAWNS: "White has too many pawns.",
    chess.STATUS_TOO_MANY_BLACK_PAWNS: "Black has too many pawns.", chess.STATUS_PAWNS_ON_BACKRANK: "A pawn cannot stand on the first or last rank.",
    chess.STATUS_TOO_MANY_WHITE_PIECES: "White has too many pieces.", chess.STATUS_TOO_MANY_BLACK_PIECES: "Black has too many pieces.",
    chess.STATUS_OPPOSITE_CHECK: "The side that is not to move cannot be in check.", chess.STATUS_TOO_MANY_CHECKERS: "That check is impossible.",
    chess.STATUS_IMPOSSIBLE_CHECK: "That check is impossible.", chess.STATUS_BAD_CASTLING_RIGHTS: "Those castling rights do not match the pieces.",
}


def build_fen(cells: dict[int, str], user_white: bool, turn: str = "w", castling: str = "-") -> tuple[str | None, str]:
    """(FEN, "") for a legal position, or (None, what is wrong). castling "auto" keeps the rights of every
    king and rook that still stands on its home square."""
    color = "w" if user_white else "b"
    if castling == "auto":
        probe = chess.Board(placement_to_fen(cells, color, turn, "-"))
        rights = ""
        for side, king, rook, symbol in ((chess.WHITE, chess.E1, chess.H1, "K"), (chess.WHITE, chess.E1, chess.A1, "Q"),
                                         (chess.BLACK, chess.E8, chess.H8, "k"), (chess.BLACK, chess.E8, chess.A8, "q")):
            k, r = probe.piece_at(king), probe.piece_at(rook)
            if k and k.piece_type == chess.KING and k.color == side and r and r.piece_type == chess.ROOK and r.color == side:
                rights += symbol
        castling = rights or "-"
    board = chess.Board(placement_to_fen(cells, color, turn, castling))
    status = board.status()
    if status == chess.STATUS_VALID:
        return board.fen(), ""
    return None, ([text for flag, text in PROBLEMS.items() if status & flag] or ["That position is not valid."])[0]


def read_position(analysis: dict, known_user_white: bool | None = None) -> dict | None:
    """Turn a recognised picture into a position: which side is at the bottom, whose move it is, the FEN.

    Both ways round are tried and the one that makes a legal position wins; when both do, the side
    whose pawns are nearer the bottom is the user."""
    reading = analysis.get("reading")
    if not reading:
        return None
    colour_of = {s: g["color"] for g in analysis["groups"] for s in g["squares"]}
    cells = {s: (kind.upper() if colour_of[s] == "w" else kind) for s, kind in reading["kinds"].items()}

    def mean_row(symbol):
        rows = [s // 8 for s, v in cells.items() if v == symbol]
        return sum(rows) / len(rows) if rows else None

    white_rows, black_rows = mean_row("P"), mean_row("p")
    prefer_white = True if white_rows is None or black_rows is None else white_rows > black_rows
    if known_user_white is not None:  # the side at the bottom is already known: only that orientation is tried
        prefer_white = known_user_white
    guessed = analysis.get("turn")
    for user_white in ([prefer_white] if known_user_white is not None else [prefer_white, not prefer_white]):
        for turn in ([guessed] if guessed else [("w" if user_white else "b")]) + ["w", "b"]:
            fen, _ = build_fen(cells, user_white, turn, "auto")
            if fen:
                return {"fen": fen, "userColor": "white" if user_white else "black", "turn": turn, "turnKnown": bool(guessed) and turn == guessed}
    return None
