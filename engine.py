"""Stockfish wrapper: best move, evaluation and multi-PV alternatives."""

import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

MATE_SCORE = 10000
PROJECT_DIR = Path(__file__).resolve().parent


class EngineNotFound(RuntimeError):
    pass


def find_stockfish(explicit: str | None = None) -> str:
    candidates = [explicit, os.environ.get("STOCKFISH_PATH")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pattern = str(PROJECT_DIR / "bin" / "**" / "stockfish*.exe")
    found = sorted(glob.glob(pattern, recursive=True))
    if found:
        return found[0]
    pattern = str(PROJECT_DIR / "bin" / "**" / "stockfish*")
    found = [p for p in sorted(glob.glob(pattern, recursive=True)) if Path(p).is_file()]
    if found:
        return found[0]
    on_path = shutil.which("stockfish")
    if on_path:
        return on_path
    raise EngineNotFound(
        "Stockfish not found. Download it from https://stockfishchess.org/download/ "
        "and either put it under chess-assistant/bin/, add it to PATH, "
        "or set the STOCKFISH_PATH environment variable."
    )


@dataclass(frozen=True)
class Line:
    """One candidate line from the engine."""

    move: chess.Move
    san: str
    score: chess.engine.PovScore
    pv: tuple[chess.Move, ...]
    pv_san: tuple[str, ...]

    def cp(self, color: bool) -> int:
        """Centipawn score from `color`'s point of view (mates become +/-10000)."""
        return self.score.pov(color).score(mate_score=MATE_SCORE)

    def mate(self, color: bool) -> int | None:
        """Moves to mate from `color`'s view: positive = color mates, negative = color gets mated."""
        return self.score.pov(color).mate()


class Engine:
    def __init__(self, path: str | None = None, time_limit: float = 0.5, multipv: int = 3):
        self.path = find_stockfish(path)
        self.time_limit = time_limit
        self.multipv = multipv
        self._engine = chess.engine.SimpleEngine.popen_uci(self.path, timeout=60)

    def analyse(self, board: chess.Board) -> list[Line]:
        """Top lines for the position, best first. Empty if the game is over."""
        if board.is_game_over():
            return []
        count = max(1, min(self.multipv, board.legal_moves.count()))
        infos = self._engine.analyse(
            board, chess.engine.Limit(time=self.time_limit), multipv=count
        )
        lines = []
        for info in infos:
            pv = tuple(info.get("pv", ()))
            if not pv:
                continue
            replay = board.copy(stack=False)
            pv_san = []
            for move in pv[:6]:
                pv_san.append(replay.san(move))
                replay.push(move)
            lines.append(
                Line(
                    move=pv[0],
                    san=board.san(pv[0]),
                    score=info["score"],
                    pv=pv,
                    pv_san=tuple(pv_san),
                )
            )
        return lines

    def best_move(self, board: chess.Board) -> chess.Move | None:
        lines = self.analyse(board)
        return lines[0].move if lines else None

    def close(self) -> None:
        try:
            self._engine.quit()
        except (chess.engine.EngineTerminatedError, OSError):
            pass

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
