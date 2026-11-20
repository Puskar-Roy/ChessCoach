"""Measure how reliably the board reader finds moves on simulated chess websites.

    python tools/benchmark_vision.py            # quick run
    python tools/benchmark_vision.py --games 6  # more games per setting

Every ply of a random game is drawn the way a website draws it (theme, piece set, last-move highlight,
check glow, coordinates, sometimes a user arrow, sometimes video compression), read back by the real
pipeline and compared with the move that was played."""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import chess
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import sitegen  # noqa: E402
from screen_reader import ScreenReader  # noqa: E402
from calibration import WARP_SIZE  # noqa: E402
from move_inference import expected_grid, infer_moves  # noqa: E402
from vision_infer import read_move  # noqa: E402


def random_game(rng: np.random.Generator, plies: int):
    board = chess.Board()
    for _ in range(plies):
        if board.is_game_over():
            return
        moves = list(board.legal_moves)
        special = [m for m in moves if board.is_capture(m) or board.is_castling(m) or m.promotion == chess.QUEEN]
        pool = special if special and rng.random() < 0.35 else moves
        move = pool[int(rng.integers(len(pool)))]
        if move.promotion and move.promotion != chess.QUEEN:
            move = chess.Move(move.from_square, move.to_square, chess.QUEEN)
        yield board.copy(), move
        board.push(move)


def warp(image: np.ndarray) -> np.ndarray:
    return cv2.resize(image, (WARP_SIZE, WARP_SIZE), interpolation=cv2.INTER_AREA)


def run(user_color: bool, theme: str, style: str, rng, plies: int, video: bool, online: bool = True, reader_factory=lambda: ScreenReader(augment=True)):
    cell = int(rng.integers(48, 100))
    start = chess.Board()

    def render(board, move=None, arrows=()):
        img = sitegen.render_board(board, user_color, cell, theme, style, last_move=move,
                                   highlight=str(rng.choice(list(sitegen.HIGHLIGHTS))), arrows=arrows, rng=rng)
        if video:
            img = sitegen.screen_share(img, int(rng.integers(55, 85)), float(rng.uniform(0.4, 0.9)), float(rng.uniform(0.75, 1.0)))
        return warp(img)

    reader = reader_factory()
    reader.learn(render(start), expected_grid(start, user_color))
    ok = missed = wrong = 0
    started = time.perf_counter()
    for before, move in random_game(rng, plies):
        after = before.copy()
        after.push(move)
        arrows = ()
        if rng.random() < 0.12:  # a user-drawn arrow somewhere on the board
            a, b = rng.choice(64, 2, replace=False)
            arrows = ((int(a), int(b)),)
        image = render(after, move, arrows)
        occupied, white = reader.read_scores(image)
        reading = read_move(before, occupied, white, user_color)
        moves = list(reading.moves) if reading.status == "move" else []
        if moves and moves[0] == move and len(moves) == 1:
            ok += 1
            if online:  # a confirmed position becomes a new training picture
                reader.add_example(image, expected_grid(after, user_color))
        elif not moves:
            missed += 1
        else:
            wrong += 1
    return ok, missed, wrong, time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=2, help="games per theme/style/colour")
    parser.add_argument("--plies", type=int, default=40)
    parser.add_argument("--video", action="store_true", help="add screen-share compression and softness")
    parser.add_argument("--no-online", action="store_true", help="do not learn from confirmed positions")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    totals = defaultdict(lambda: [0, 0, 0])
    elapsed = 0.0
    count = 0
    for theme in sitegen.THEMES:
        for style in sitegen.PIECE_STYLES:
            for color in (chess.WHITE, chess.BLACK):
                for _ in range(args.games):
                    ok, missed, wrong, seconds = run(color, theme, style, rng, args.plies, args.video, not args.no_online)
                    for key in ("all", f"theme:{theme}", f"style:{style}"):
                        totals[key][0] += ok
                        totals[key][1] += missed
                        totals[key][2] += wrong
                    elapsed += seconds
                    count += ok + missed + wrong
    print(f"{'setting':<18}{'moves':>7}{'correct':>9}{'missed':>8}{'WRONG':>7}")
    for key in sorted(totals, key=lambda k: (k != "all", k)):
        ok, missed, wrong = totals[key]
        n = ok + missed + wrong
        print(f"{key:<18}{n:>7}{100 * ok / n:>8.2f}%{100 * missed / n:>7.2f}%{100 * wrong / n:>6.2f}%")
    print(f"\n{count} moves, {1000 * elapsed / count:.1f} ms per move (reading + inference)")
    ok, missed, wrong = totals["all"]
    return 0 if wrong == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
