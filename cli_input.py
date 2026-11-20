"""Manual input: classify a typed line as a command or a move."""

import queue
import threading
from dataclasses import dataclass

COMMANDS = {
    "help": "help",
    "?": "help",
    "undo": "undo",
    "takeback": "undo",
    "hint": "hint",
    "repeat": "repeat",
    "again": "repeat",
    "board": "board",
    "moves": "moves",
    "mute": "mute",
    "unmute": "unmute",
    "resign": "resign",
    "new": "new",
    "newgame": "new",
    "quit": "quit",
    "exit": "quit",
    "q": "quit",
}

HELP_TEXT = """Type each move as it is played (yours AND your opponent's), in standard notation:
  e4   Nf3   exd5   O-O   Qxf7#   e8=Q      (UCI like e2e4 also works)
Commands:
  hint      best move for you right now
  repeat    say the last advice again
  undo      take back the last move
  new       start a new game from the starting position (key N in the camera/screen window)
  board     show the board
  moves     show the move list
  mute / unmute   turn the voice off / on (key M in the camera/screen window)
  resign    give up the game
  quit      exit"""


@dataclass(frozen=True)
class Command:
    kind: str  # "move", "camera_moves", or one of COMMANDS' values
    text: str = ""
    moves: tuple = ()  # chess.Move objects, for "camera_moves"


def parse_line(line: str) -> Command:
    stripped = line.strip()
    kind = COMMANDS.get(stripped.lower())
    if kind:
        return Command(kind)
    return Command("move", stripped)


class CommandReader:
    """Reads typed lines on a background thread, so the camera loop can keep running."""

    def __init__(self):
        self._queue: queue.Queue[Command] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                line = input()
            except EOFError:
                self._queue.put(Command("quit"))
                return
            except OSError:
                return
            self._queue.put(parse_line(line))

    def get(self, timeout: float | None = None) -> Command | None:
        """Next typed command, or None if nothing arrived within `timeout` seconds."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
