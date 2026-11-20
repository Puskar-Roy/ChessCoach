"""Opening lookup: name the opening/gambit being played and give plan notes."""

import json
from dataclasses import dataclass
from pathlib import Path

import chess

DATA_FILE = Path(__file__).resolve().parent / "data" / "openings.json"


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str
    moves: tuple[str, ...]
    plan_white: str
    plan_black: str
    trap: str | None = None

    def plan_for(self, color: bool) -> str:
        return self.plan_white if color == chess.WHITE else self.plan_black


@dataclass(frozen=True)
class OpeningMatch:
    opening: Opening
    ply: int  # how many half-moves into the game the book position occurred
    current: bool  # True if the game is still exactly at that position


class OpeningBook:
    def __init__(self, openings: list[Opening]):
        self.openings = openings
        self._by_epd: dict[str, Opening] = {}
        for opening in openings:
            board = chess.Board()
            for san in opening.moves:
                board.push_san(san)
            # keep the first entry for a position so earlier, more general entries win ties
            self._by_epd.setdefault(board.epd(), opening)

    @classmethod
    def load(cls, path: Path = DATA_FILE) -> "OpeningBook":
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        openings = [
            Opening(
                eco=item["eco"],
                name=item["name"],
                moves=tuple(item["moves"].split()),
                plan_white=item["plan_white"],
                plan_black=item["plan_black"],
                trap=item.get("trap"),
            )
            for item in raw
        ]
        return cls(openings)

    def identify(self, board: chess.Board) -> OpeningMatch | None:
        """Most recent book position reached in this game (handles transpositions)."""
        replay = board.root()
        positions = [replay.epd()]
        for move in board.move_stack:
            replay.push(move)
            positions.append(replay.epd())
        for ply in range(len(positions) - 1, 0, -1):
            opening = self._by_epd.get(positions[ply])
            if opening:
                return OpeningMatch(opening, ply, ply == len(positions) - 1)
        return None
