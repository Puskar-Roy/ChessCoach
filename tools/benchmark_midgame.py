"""How well does the app read a game that is already under way?

    python tools/benchmark_midgame.py SETS_DIR [--only PREFIX] [--model FILE] [--boards N]

Random mid-game positions are drawn with real piece sets (the folders of SETS_DIR) on random board colours,
then read by the same code the app uses. Pass a model that was trained WITHOUT those sets for an honest number.
"""

import argparse
import sys
from pathlib import Path

import chess
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

import piece_classifier  # noqa: E402
import sitegen  # noqa: E402
from move_inference import square_to_cell  # noqa: E402
from piece_cluster import analyse_position, read_position  # noqa: E402
from train_pieces import load_set  # noqa: E402

SURE_ENOUGH = 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sets")
    parser.add_argument("--only", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--boards", type=int, default=120)
    parser.add_argument("-v", action="store_true")
    args = parser.parse_args()
    if args.model:
        piece_classifier._model = piece_classifier.PieceModel.load(Path(args.model))
    sets = {f.name: load_set(f) for f in sorted(Path(args.sets).iterdir()) if f.is_dir() and f.name.startswith(tuple(args.only.split(",")))}
    sets = {n: s for n, s in sets.items() if len(s) == 12}
    rng = np.random.default_rng(77)
    names = list(sets)
    totals = dict(boards=0, exact=0, confident=0, confident_wrong=0, squares=0, squares_ok=0, side_ok=0, turn_ok=0, turn_known=0, none=0)
    per_set = {}
    sures = []
    for i in range(args.boards):
        name = names[i % len(names)]
        sprites = sets[name]

        def sprite(symbol, px, style, sprites=sprites):
            image = sprites[("w" if symbol.isupper() else "b") + symbol.lower()]
            image = cv2.resize(image, (px, px), interpolation=cv2.INTER_AREA)
            return np.dstack([image[:, :, 2], image[:, :, 1], image[:, :, 0], image[:, :, 3]]).astype(np.float32)

        sitegen._sprite = sprite
        board = chess.Board()
        for _ in range(int(rng.integers(10, 70))):
            if board.is_game_over():
                break
            board.push(rng.choice(list(board.legal_moves)))
        if board.is_game_over() or not board.move_stack:
            continue
        user = chess.WHITE if rng.random() < 0.5 else chess.BLACK
        theme = list(sitegen.THEMES)[int(rng.integers(len(sitegen.THEMES)))]
        image = sitegen.render_board(board, user, int(rng.integers(52, 100)), theme, "classic", last_move=board.peek(), highlight=("yellow", "lime")[int(rng.integers(2))], rng=rng)
        warped = cv2.resize(image, (480, 480), interpolation=cv2.INTER_AREA)
        result = analyse_position(warped)
        totals["boards"] += 1
        stats = per_set.setdefault(name, [0, 0])
        stats[0] += 1
        reading = result.get("reading") if result["ok"] else None
        position = read_position(result) if reading else None
        if position is None:
            totals["none"] += 1
            continue
        truth = {}
        for square, piece in board.piece_map().items():
            row, col = square_to_cell(square, user)
            truth[row * 8 + col] = piece.piece_type
        colour_of = {s: g["color"] for g in result["groups"] for s in g["squares"]}
        ok = 0
        for s, kind in reading["kinds"].items():
            totals["squares"] += 1
            good = s in truth and chess.piece_symbol(truth[s]) == kind
            ok += good
            totals["squares_ok"] += good
        exact = ok == len(truth) == len(reading["kinds"]) and chess.Board(position["fen"]).board_fen() == board.board_fen()
        sure = reading["sure"] >= SURE_ENOUGH
        totals["exact"] += exact
        totals["confident"] += sure
        totals["confident_wrong"] += sure and not exact
        stats[1] += exact
        totals["side_ok"] += position["userColor"] == ("white" if user == chess.WHITE else "black")
        if position["turnKnown"]:
            totals["turn_known"] += 1
            totals["turn_ok"] += position["turn"] == ("w" if board.turn == chess.WHITE else "b")
        sures.append((reading["sure"], exact))
        if not exact and sure and "-v" in sys.argv:
            print("WRONG", round(reading["sure"], 3), name, theme, board.fen(), "->", position["fen"])
    t = totals
    n = max(t["boards"], 1)
    print(f"boards {t['boards']}  read {n - t['none']}  piece kinds right {t['squares_ok']}/{t['squares']} = {t['squares_ok'] / max(t['squares'], 1):.3%}")
    print(f"whole board exactly right {t['exact']}/{n} = {t['exact'] / n:.1%};  used without asking {t['confident']}  of which wrong {t['confident_wrong']}")
    print(f"side at the bottom right {t['side_ok']}/{n};  side to move known {t['turn_known']}, right {t['turn_ok']}")
    for limit in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8):
        kept = [e for v, e in sures if v >= limit]
        print(f"  sure>={limit}: used {len(kept)}/{len(sures)}, wrong {sum(1 for e in kept if not e)}")
    worst = sorted(per_set.items(), key=lambda kv: kv[1][1] / max(kv[1][0], 1))[:6]
    print("hardest sets:", ", ".join(f"{k} {v[1]}/{v[0]}" for k, v in worst))


if __name__ == "__main__":
    main()
