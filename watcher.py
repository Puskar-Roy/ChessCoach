"""Watches a chess board on the screen and reports the moves that are played.

This is the live pipeline: it waits until the picture is still, takes several frames and averages what the
reader sees (so a flicker or an animation frame cannot fool it), works out the move(s) with the rules of
chess, and keeps checking that the board is still where it was. If the page scrolls, resizes or the
window moves, it finds the board again by itself. Nothing here opens a window: a UI sits on top."""

import sys
import time
from dataclasses import dataclass, field

import chess
import cv2
import numpy as np

from board_detect import detect_boards, lattice_strength
from catch_up import bitboards_from_grid, find_moves, kind_masks, plausible_successor
from calibration import WARP_SIZE
from move_inference import expected_grid
from screen_reader import ScreenReader, cell_features
from vision_infer import read_move

STILL_FRAMES = 6  # consecutive calm frames before we look
STILL_SECONDS = 0.35  # ... and this much calm time (piece slide animations last about 0.3 s)
MOTION_THRESHOLD = 6.0  # gray-level change in any square between frames that counts as movement
VOTE_FRAMES = 3  # frames averaged for one reading
VOTE_GAP = 0.04
RETRY_DELAYS = (0.6, 1.2, 2.4, 3.0)  # seconds between re-reads of a picture we could not understand
CHECK_EVERY = 1.0  # how often the board position on screen is verified
LOST_AFTER = 3  # failed checks in a row before the board is considered lost
CONFIDENT_MARGIN = 6.0  # a reading this clear is added to the reader's training pictures
CONFIDENT_REGRET = 3.0
UNEXPLAINED_REGRET = 14.0  # nats: a reading this far from every legal continuation is probably not our board


ADOPT_AFTER = 5  # failed readings (about 12 seconds) before the position on the screen is taken as it is
ADOPT_SURE = 0.75


class WatchError(RuntimeError):
    pass


def mouse_button_down() -> bool:
    """True while a mouse button is held: a piece is being dragged and the board is not showing a position."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        state = ctypes.windll.user32.GetAsyncKeyState
        return bool(state(0x01) & 0x8000 or state(0x02) & 0x8000)  # left or right button
    except Exception:
        return False


@dataclass
class WatchEvent:
    kind: str  # "moves" | "takeback" | "resync" | "unclear" | "lost" | "relocked"
    moves: list[chess.Move] = field(default_factory=list)
    plies: int = 0  # "takeback": how many moves were taken back
    fen: str = ""  # "resync": the position now on the screen
    message: str = ""
    doubtful: tuple[str, ...] = ()
    region: tuple[int, int, int, int] | None = None  # (x, y, w, h) on the monitor, for "relocked"
    image: np.ndarray | None = None  # "unclear": the board picture that could not be read (for the debug record)


@dataclass(frozen=True)
class StartCheck:
    ok: bool
    user_color: bool | None
    message: str


def to_board_image(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(frame, (WARP_SIZE, WARP_SIZE), interpolation=cv2.INTER_AREA)


def check_start_position(warped: np.ndarray) -> StartCheck:
    """Is this picture a fresh game, and which side is at the bottom?

    A start position has all 16 squares of the two bottom ranks and the two top ranks occupied, and the
    four middle ranks empty; the side whose pieces are lighter is White."""
    occupancy, colour = cell_features(warped)
    presence = occupancy[:, 0].reshape(8, 8)  # share of the square's middle that differs from its own background
    rows_full = np.array([0, 1, 6, 7])
    rows_empty = np.array([2, 3, 4, 5])
    full, empty = presence[rows_full], presence[rows_empty]
    seen = int((presence > 0.25).sum())  # squares that clearly hold a piece
    threshold = 0.5 * (np.median(full) + np.median(empty))
    wrong = int((full < threshold).sum() + (empty >= threshold).sum())
    if np.median(full) < 0.15 or wrong > 4:
        if seen == 0:
            return StartCheck(False, None, "I can't see any pieces on that board. Is something covering it?")
        return StartCheck(False, None, "This is not the starting position, so this game is already under way.")
    light = colour[:, 0].reshape(8, 8)
    top, bottom = float(np.median(light[:2])), float(np.median(light[6:]))
    if abs(top - bottom) < 0.04:
        return StartCheck(False, None, "I can't tell the white pieces from the black ones. Check the board colours.")
    return StartCheck(True, chess.WHITE if bottom > top else chess.BLACK, "")


class BoardWatcher:
    def __init__(self, capture, user_color: bool, reader: ScreenReader | None = None, clock=time.monotonic, sleep=time.sleep, mouse_down=None):
        """`capture.read()` returns (ok, BGR frame of the board region); `capture.read_monitor()` the whole screen."""
        self.capture = capture
        self.user_color = user_color
        self.reader = reader or ScreenReader(augment=True)
        self._clock = clock
        self._sleep = sleep
        self._mouse_down = mouse_down or (lambda: mouse_button_down())
        self._previous: np.ndarray | None = None
        self._still = 0
        self._still_since = 0.0
        self._handled = True
        self._reported = False
        self._attempts = 0
        self._next_try = 0.0
        self._next_check = 0.0
        self._baseline = 0.0
        self._bad_checks = 0
        self.lost = False
        self._unexplained = 0  # readings in a row that no legal move can explain
        self.last_doubtful: tuple[str, ...] = ()

    # ------------------------------------------------------------------ setup
    def _frame(self) -> np.ndarray:
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise WatchError("Lost the screen feed.")
        return to_board_image(frame)

    def prepare(self, board: chess.Board):
        """Learn what this board looks like from the current (known) position. Raises ValueError if it cannot."""
        frames = []
        for _ in range(3):
            frames.append(self._frame())
            self._sleep(0.03)
        image = frames[1]
        report = self.reader.learn(image, expected_grid(board, self.user_color))
        self._baseline = max(lattice_strength(image), 1e-6)
        self.resync()
        return report

    def resync(self) -> None:
        """Forget the picture history (call after slow work such as engine analysis)."""
        self._previous = None
        self._still = 0
        self._handled = True

    def reread(self) -> None:
        """Read the board again as soon as it is still, even if the last reading was already handled."""
        self._handled = False
        self._reported = False
        self._attempts = 0
        self._next_try = 0.0

    def close(self) -> None:
        release = getattr(self.capture, "release", None)
        if release:
            release()

    def status(self) -> str:
        if self.lost:
            return "lost"
        return "watching" if self._is_still(self._clock()) else "settling"

    def _is_still(self, now: float) -> bool:
        return self._still >= STILL_FRAMES and now - self._still_since >= STILL_SECONDS

    # ------------------------------------------------------------------- step
    def step(self, board: chess.Board) -> WatchEvent | None:
        warped = self._frame()
        now = self._clock()
        small = cv2.resize(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
        if self._mouse_down():  # a piece is being dragged (or an arrow drawn): whatever the picture shows is not a position
            self._still = 0
            self._still_since = now
            self._handled = False
            self._reported = False
            self._attempts = 0
            self._next_try = 0.0
            self._previous = small
            self._unexplained = 0
        elif self._previous is not None and _max_cell_change(small, self._previous) < MOTION_THRESHOLD:
            self._still += 1
        else:
            self._still = 0
            self._still_since = now
            self._handled = False
            self._reported = False
            self._attempts = 0
            self._next_try = 0.0
        self._previous = small

        if now >= self._next_check:
            self._next_check = now + CHECK_EVERY
            event = self._verify_alignment(warped)
            if event is not None:
                return event
        if self.lost:
            return None
        if self._is_still(now) and not self._handled and now >= self._next_try:
            return self._interpret(board, warped, now)
        return None

    def _interpret(self, board: chess.Board, first: np.ndarray, now: float) -> WatchEvent | None:
        images = [first]
        for _ in range(VOTE_FRAMES - 1):
            self._sleep(VOTE_GAP)
            images.append(self._frame())
        occupied = np.zeros((8, 8))
        white = np.zeros((8, 8))
        for image in images:
            occ, wh = self.reader.read_scores(image)
            occupied += occ / len(images)
            white += wh / len(images)
        reading = read_move(board, occupied, white, self.user_color)
        self.last_doubtful = reading.doubtful
        if reading.status == "move":
            self._handled = True
            self._unexplained = 0
            if reading.margin >= CONFIDENT_MARGIN and reading.regret <= CONFIDENT_REGRET:
                after = board.copy(stack=False)
                for move in reading.moves:
                    after.push(move)
                self.reader.add_example(images[len(images) // 2], expected_grid(after, self.user_color))
            return WatchEvent("moves", list(reading.moves))
        if reading.status == "unchanged":
            self._handled = True
            return None
        if self._attempts >= 1:  # more moves than the quick reader weighs may have been played: search for them
            for attempt in (self._take_back, self._catch_up):
                found = attempt(board, images, occupied, white)
                if found is not None:
                    return found
        if self._attempts >= ADOPT_AFTER:  # nothing explains it as moves: take the position as it is on the screen
            found = self._adopt_picture(board, images)
            if found is not None:
                return found
        self._next_try = now + RETRY_DELAYS[min(self._attempts, len(RETRY_DELAYS) - 1)]
        self._attempts += 1
        # A picture no sequence of moves can explain usually means the board is not where we are looking.
        self._unexplained = self._unexplained + 1 if reading.regret > UNEXPLAINED_REGRET else 0
        if self._unexplained >= 2:
            event = self._relocate(report_lost=False)
            if event is not None:
                return event
        if self._reported:
            return None
        self._reported = True
        where = ", ".join(reading.doubtful[:6]) or "?"
        return WatchEvent("unclear", message=f"I couldn't tell what changed (unsure around: {where}).", doubtful=reading.doubtful, image=images[len(images) // 2])

    def _take_back(self, board: chess.Board, images, occupied: np.ndarray, white: np.ndarray) -> WatchEvent | None:
        """The player took moves back (chess sites offer that against the computer): the picture shows an earlier position."""
        white_bb, black_bb, unsure = bitboards_from_grid(occupied, white, self.user_color)
        care = chess.BB_ALL & ~unsure
        earlier = board.copy()
        for plies in range(1, len(earlier.move_stack) + 1):
            earlier.pop()
            if ((earlier.occupied_co[chess.WHITE] ^ white_bb) & care).bit_count() + ((earlier.occupied_co[chess.BLACK] ^ black_bb) & care).bit_count() == 0:
                self._handled = True
                self._unexplained = 0
                return WatchEvent("takeback", plies=plies, message=f"You took back {plies} move{'s' if plies != 1 else ''}.")
        return None

    def _adopt_picture(self, board: chess.Board, images) -> WatchEvent | None:
        """Read the whole position from the picture (a new game, or too many moves at once to follow)."""
        try:
            from piece_cluster import analyse_position, read_position

            analysis = analyse_position(images[len(images) // 2])
            if not analysis.get("ok") or (analysis.get("reading") or {}).get("sure", 0) < ADOPT_SURE:
                return None
            position = read_position(analysis, self.user_color == chess.WHITE)
        except Exception:
            return None
        if position is None or not plausible_successor(board, chess.Board(position["fen"])):
            return None  # a half-made move or a misreading, not a position this game can have reached
        self._handled = True
        self._unexplained = 0
        return WatchEvent("resync", fen=position["fen"], message="I couldn't follow the last changes move by move, so I re-read the whole position.")

    def _catch_up(self, board: chess.Board, images: list[np.ndarray], occupied: np.ndarray, white: np.ndarray) -> WatchEvent | None:
        """The picture is several moves ahead of our position: find the moves that lead there."""
        white_bb, black_bb, unsure = bitboards_from_grid(occupied, white, self.user_color)
        masks = None
        try:
            from piece_cluster import analyse_position

            analysis = analyse_position(images[len(images) // 2])
            reading = analysis.get("reading") if analysis.get("ok") else None
            if reading:
                colour_of = {s: g["color"] for g in analysis["groups"] for s in g["squares"]}
                masks = kind_masks(reading["kinds"], colour_of, self.user_color)
        except Exception:
            masks = None  # without piece kinds the squares alone still decide
        moves = find_moves(board, white_bb, black_bb, masks, unsure)
        if not moves:
            return None
        self._handled = True
        self._unexplained = 0
        return WatchEvent("moves", moves, message=f"I had missed {len(moves)} moves, so I caught up.")

    # ---------------------------------------------------------------- tracking
    def _verify_alignment(self, warped: np.ndarray) -> WatchEvent | None:
        strength = lattice_strength(warped) / self._baseline if self._baseline else 1.0
        if not self.lost:
            self._bad_checks = self._bad_checks + 1 if strength < 0.45 else 0
            if self._bad_checks < LOST_AFTER:
                return None
            self.lost = True
        elif strength >= 0.7:
            self.lost = False
            self._bad_checks = 0
            self.resync()
            return WatchEvent("relocked", message="The board is back.")
        return self._relocate(report_lost=True)

    def _relocate(self, report_lost: bool) -> WatchEvent | None:
        """The board is no longer where we expect: look for it on the whole screen."""
        try:
            screen = self.capture.read_monitor()
        except Exception:
            return None
        current = self.capture.region
        size = current["width"]
        for found in detect_boards(screen, limit=3):
            if found.confidence >= 0.6 and abs(found.size - size) <= 0.2 * size:
                here = (found.x + self.capture.monitor_left, found.y + self.capture.monitor_top)
                if abs(here[0] - current["left"]) <= 3 and abs(here[1] - current["top"]) <= 3 and abs(found.size - size) <= 3:
                    self._unexplained = 0
                    return None  # the board is exactly where we look: something else is wrong
                self.capture.set_region(found.x, found.y, found.size, found.size)  # relative to the monitor
                self.lost = False
                self._bad_checks = 0
                self.resync()
                region = self.capture.region
                return WatchEvent("relocked", message="The board moved. I found it again.",
                                  region=(region["left"], region["top"], region["width"], region["height"]))
        if report_lost and self._bad_checks == LOST_AFTER:
            self._bad_checks += 1  # report "lost" once, keep looking quietly
            return WatchEvent("lost", message="I can't see the board. Is it hidden or scrolled away?")
        return None


def _max_cell_change(current: np.ndarray, previous: np.ndarray) -> float:
    diff = np.abs(current - previous).reshape(8, 8, 8, 8)
    return float(diff.mean(axis=(1, 3)).max())
