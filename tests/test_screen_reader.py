"""Accuracy gate for the board reader on simulated websites (a quick version of tools/benchmark_vision.py)."""

import sys
from pathlib import Path

import chess
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import benchmark_vision as bench  # noqa: E402


@pytest.mark.parametrize("video", [False, True], ids=["lossless", "screen-share"])
def test_moves_are_read_correctly_and_never_wrongly(video):
    rng = np.random.default_rng(17)
    ok = missed = wrong = 0
    for theme, style in (("green", "classic"), ("brown", "neo"), ("midnight", "classic"), ("blue", "wood")):
        for color in (chess.WHITE, chess.BLACK):
            a, b, c, _ = bench.run(color, theme, style, rng, plies=24, video=video)
            ok, missed, wrong = ok + a, missed + b, wrong + c
    total = ok + missed + wrong
    assert wrong == 0, f"{wrong} wrong moves out of {total}"
    assert ok / total >= 0.97, f"only {100 * ok / total:.1f}% of {total} moves read"
