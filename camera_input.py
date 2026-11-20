"""Live camera input: calibrate once, then turn physical moves into chess moves.

Run this file directly to test the camera/lighting without the engine:
    python camera_input.py --color white
"""

import argparse
import time
from dataclasses import dataclass, field

import chess
import cv2
import numpy as np

from board_reader import WHITE, BoardReader, grid_to_text
from calibration import (
    SQUARE_SIZE,
    WARP_SIZE,
    WINDOW,
    Calibration,
    pick_corners,
    put_text,
    with_header,
    wrap_text,
)
from move_inference import _cell_name, expected_grid, infer_moves, square_to_cell
from screen_capture import window_gone

BOARD_WINDOW = "Board as the computer sees it"
STILL_FRAMES = 10  # consecutive calm frames before we trust the picture
MOTION_THRESHOLD = 6.0  # gray-level change in any one square between frames that counts as movement
MAX_LEARN_ERRORS = 4
STILL_SECONDS = 0.4  # a screen is read very fast, so also require this much calm time (piece slide animations)
RETRY_SECONDS = 0.6  # re-read an unclear picture this often until it is clear or changes
SUBTITLE_HEIGHT = 200  # extra strip under the board in the screen-mode status window
SUBTITLE_LINE = 22
HEADER_HEIGHT = 140  # room for the status and key hints above the board in the screen-mode window
SUBTITLE_SCALE = 0.55


@dataclass
class CameraEvent:
    kind: str  # "moves" | "unclear" | "quit" | "toggle_mute" | "hint" | "new_game"
    moves: list[chess.Move] = field(default_factory=list)
    message: str = ""
    grid: np.ndarray | None = None


class CameraError(RuntimeError):
    pass


class CameraSession:
    def __init__(self, user_color: bool, camera_index: int = 0, screen: int | None = None):
        """`screen` is a monitor number (1 = primary) to read the board from the screen instead of a webcam."""
        self.user_color = user_color
        self.camera_index = camera_index
        self.screen = screen
        self.reader = BoardReader(augment=screen is not None)
        self.calibration: Calibration | None = None
        self._capture = None
        self._previous: np.ndarray | None = None
        self._still = 0
        self._handled = True
        self._last_grid: np.ndarray | None = None
        self._window_placed = True
        self._hidden = False
        self._presented = 0
        self._warned_visible = False
        self._still_since = 0.0
        self._next_try = 0.0
        self._reported_unclear = False
        self.expected_note = "the starting position"  # what the position on the board must be while learning
        self.status = ""  # one-line state shown in the window, set by main.py
        self.subtitle = ""
        self.arrows_on = True
        self.headless = False  # True once an app UI replaces this module's windows
        self.progress = print  # where setup messages go (an app can redirect them)
        self._arrow: chess.Move | None = None
        self._overlay = None
        self._notice: tuple[str, float] | None = None
        self.subtitles_on = True
        self.muted = False  # kept in sync by main.py, only used for the on-screen hint

    def open(self) -> None:
        if self.screen is not None:
            self._open_screen()
            return
        capture = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            raise CameraError(f"Could not open camera {self.camera_index}.")
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._capture = capture
        cv2.namedWindow(WINDOW)
        for _ in range(5):  # let auto-exposure settle
            capture.read()

    def _open_screen(self) -> None:
        from screen_capture import ScreenCapture, ScreenCaptureError

        try:
            capture = ScreenCapture(self.screen)
            self.progress("Screen mode: bring the chess board into view; a screenshot is taken after a short countdown.")
            if not capture.select_region(progress=self.progress):
                capture.release()
                raise CameraError("No board area selected.")
        except ScreenCaptureError as error:
            raise CameraError(str(error)) from error
        self._capture = capture
        cv2.namedWindow(WINDOW)
        self._window_placed = False

    def close(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        cv2.destroyAllWindows()

    def _read(self) -> np.ndarray:
        assert self._capture is not None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError("Lost the board feed." if self.screen is not None else "Lost the camera feed.")
        return frame

    def show_move(self, move: chess.Move | None) -> None:
        """Draw the suggested move as an arrow on the board (None removes it)."""
        self._arrow = move
        self._refresh_overlay()

    def _cell_center(self, square: int) -> tuple[float, float]:
        row, col = square_to_cell(square, self.user_color)
        return (col + 0.5) * SQUARE_SIZE, (row + 0.5) * SQUARE_SIZE

    def _refresh_overlay(self) -> None:
        """Arrow on the real screen (screen mode only): a see-through window over the captured board."""
        if self.screen is None or self._capture is None:
            return
        move = self._arrow if self.arrows_on and self.calibration is not None else None
        if move is None:
            if self._overlay is not None:
                self._overlay.clear()
            return
        if self._overlay is None:
            try:
                from overlay import BoardOverlay  # the desktop app draws its own arrow; the CLI no longer ships this
            except ImportError:
                return

            region = self._capture.region
            self._overlay = BoardOverlay(region["left"], region["top"], region["width"], region["height"])
        if not self._overlay.ok:
            return
        start = self.calibration.to_frame(*self._cell_center(move.from_square))
        end = self.calibration.to_frame(*self._cell_center(move.to_square))
        step = self.calibration.to_frame(self._cell_center(move.from_square)[0] + SQUARE_SIZE,
                                         self._cell_center(move.from_square)[1])
        square = max(10.0, float(np.hypot(step[0] - start[0], step[1] - start[1])))
        self._overlay.show(start, end, square)

    def _draw_arrow(self, image: np.ndarray, project) -> None:
        """Arrow on a picture; `project` maps a point of the flat board image to this picture's pixels."""
        if self._arrow is None or not self.arrows_on:
            return
        start = project(*self._cell_center(self._arrow.from_square))
        end = project(*self._cell_center(self._arrow.to_square))
        cv2.arrowedLine(image, start, end, (0, 140, 255), 5, cv2.LINE_AA, tipLength=0.3)
        cv2.circle(image, start, 9, (80, 200, 80), 2, cv2.LINE_AA)

    def reread(self) -> None:
        """Forget what was already handled so the board is read again as soon as it is still."""
        self._handled = False
        self._reported_unclear = False
        self._next_try = 0.0

    def watch_status(self) -> str:
        """'settling' while the picture is changing, otherwise 'watching'."""
        return "watching" if self._is_still() else "settling"

    def enter_live_mode(self) -> None:
        """Close this module's own windows; from now on an app UI shows everything."""
        self.headless = True
        cv2.destroyAllWindows()
        cv2.waitKey(1)
        self.resync()

    def set_status(self, text: str) -> None:
        self.status = text

    def set_subtitle(self, text: str) -> None:
        """Show what the coach is saying as an on-screen caption (works even when the voice is muted)."""
        self.subtitle = text

    def notify(self, text: str, seconds: float = 8.0) -> None:
        """Show a short-lived message (e.g. 'could not tell the move') even if subtitles are off."""
        self._notice = (text, time.monotonic() + seconds)

    def _caption(self) -> str:
        if self._notice is not None:
            text, until = self._notice
            if time.monotonic() < until:
                return text
            self._notice = None
        return self.subtitle if self.subtitles_on else ""

    def _draw_subtitle(self, image: np.ndarray) -> None:
        """Caption in a black strip along the bottom of `image`."""
        text = self._caption()
        if not text:
            return
        width = image.shape[1]
        lines = wrap_text(text, width - 20, SUBTITLE_SCALE)
        max_lines = max(1, min(len(lines), (SUBTITLE_HEIGHT - 10) // SUBTITLE_LINE))
        lines = lines[:max_lines]
        top = image.shape[0] - 10 - SUBTITLE_LINE * len(lines)
        image[top:] = (image[top:] * 0.1).astype(np.uint8)
        for i, line in enumerate(lines):
            y = top + 8 + SUBTITLE_LINE * (i + 1) - 6
            cv2.putText(image, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, SUBTITLE_SCALE, (255, 255, 255), 1, cv2.LINE_AA)

    def _mute_label(self) -> str:
        return "unmute (voice is OFF)" if self.muted else "mute voice"

    def _present(self, view: np.ndarray) -> None:
        cv2.imshow(WINDOW, view)
        if self.screen is None:
            return
        if not self._window_placed:
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)  # keep the coach window above the browser
            # Park the window beside the captured area, never on top of it.
            self._window_placed = True
            cv2.moveWindow(WINDOW, *self._capture.free_spot(view.shape[1], view.shape[0]))
            from screen_capture import focus_window

            focus_window(WINDOW)
        self._presented += 1
        if not self._hidden or self._presented % 20 == 0:
            # Hide our own window from the capture, otherwise the board is read through it (a hall of mirrors).
            from screen_capture import hide_from_capture

            self._hidden = hide_from_capture(WINDOW)
            if not self._hidden and not self._warned_visible:
                self._warned_visible = True
                print("(Warning: this Windows version cannot hide the preview from the capture. "
                      "Move the preview window off the board.)")

    def _key(self, delay: int = 1) -> int:
        key = cv2.waitKey(delay) & 0xFF
        if self.screen is not None and window_gone(WINDOW):
            return 27  # closing the window with X counts as ESC
        return key

    def resync(self) -> None:
        """Call after anything slow (like engine analysis) so stale frames are not used."""
        if self._capture is not None:
            for _ in range(4):
                self._capture.grab()
        self._previous = None
        self._still = 0

    def setup(self, board: chess.Board) -> bool:
        """Interactive calibration + learning. Returns False if the user cancelled."""
        if self.screen is None:
            return self._setup(board)
        # Keep the prompts above the browser while setting up; the window is parked off the board.
        self._window_placed = False
        self._set_topmost(True)
        try:
            return self._setup(board)
        finally:
            self._window_placed = False
            self._refresh_overlay()  # the corners may have changed

    def _set_topmost(self, on: bool) -> None:
        cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1 if on else 0)

    def _setup(self, board: chess.Board) -> bool:
        if self.calibration is None and self.screen is None:  # a saved camera calibration means nothing for a screen
            self.calibration = Calibration.load()
        saved = self.calibration is not None
        while True:
            if not self._choose_corners(saved):
                return False
            outcome = self._learn(board)
            if outcome == "ok":
                if self.screen is None:
                    self.calibration.save()
                self.resync()
                return True
            if outcome == "cancel":
                return False
            saved = False
            self.calibration = None

    def _choose_corners(self, can_reuse: bool) -> bool:
        reuse = "  U = use saved corners" if can_reuse else ""
        if self.screen is not None:
            reuse = "  ENTER = use this area (it snaps to the board)"
        while True:
            frame = self._read()
            view = self.calibration.draw(frame) if (can_reuse and self.calibration) else frame.copy()
            view, _ = with_header(view, [
                "Show the board from YOUR side (your pieces at the bottom)." if self.screen is not None
                else "Point the camera at the board.",
                "SPACE = freeze and click corners",
                (reuse.strip() + "   " if reuse else "") + "ESC = cancel",
            ])
            self._present(view)
            key = self._key(30)
            if key == 27:
                return False
            if key in (13, 10) and self.screen is not None:
                height, width = frame.shape[:2]
                whole = [(0, height - 1), (width - 1, height - 1), (width - 1, 0), (0, 0)]
                self.calibration = Calibration.from_clicks(whole)
                return True
            if key in (ord("u"), ord("U")) and can_reuse and self.calibration:
                return True
            if key == 32:
                clicks = pick_corners(frame, self.user_color)
                if clicks is not None:
                    self.calibration = Calibration.from_clicks(clicks)
                    return True

    def _learn(self, board: chess.Board) -> str:
        """Learn what pieces look like from the position currently on the board.

        Returns "ok", "redo" (pick corners again) or "cancel"."""
        assert self.calibration is not None
        message = ""
        while True:
            frame = self._read()
            view = self.calibration.draw(frame)
            view, _ = with_header(view, [
                f"The board must show: {self.expected_note}.",
                "Keep hands off the board, then press SPACE.",
                "R = redo corners   ESC = cancel",
                message,
            ])
            self._present(view)
            key = self._key(30)
            if key == 27:
                return "cancel"
            if key in (ord("r"), ord("R")):
                return "redo"
            if key == 32:
                warped = self.calibration.warp(frame)
                try:
                    report = self.reader.learn(warped, expected_grid(board, self.user_color))
                except ValueError as error:
                    message = str(error)
                    continue
                if report.errors <= MAX_LEARN_ERRORS:
                    return "ok"
                where = ", ".join(_cell_name(r, c, self.user_color) for r, c in report.bad_cells[:8])
                message = (
                    f"Could not tell {report.errors} squares apart ({where}). Check the board shows exactly "
                    "that position, from your side, and that the corners are right. "
                    "SPACE = retry, R = redo corners."
                )

    def relearn(self, board: chess.Board) -> str:
        """Re-learn thresholds from the current position (e.g. lighting changed)."""
        if self.calibration is None:
            return "Not calibrated yet."
        frame = self._read()
        try:
            report = self.reader.learn(self.calibration.warp(frame), expected_grid(board, self.user_color))
        except ValueError as error:
            return f"Could not re-learn: {error}"
        self.resync()
        return f"Re-learned from the current position ({report.errors} unclear squares)."

    def step(self, board: chess.Board) -> CameraEvent | None:
        """Process one camera frame. Returns an event when something was seen or a key pressed."""
        assert self.calibration is not None
        frame = self._read()
        warped = self.calibration.warp(frame)
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
        now = time.monotonic()
        if self._previous is not None and _max_square_change(small, self._previous) < MOTION_THRESHOLD:
            self._still += 1
        else:
            self._still = 0
            self._still_since = now
            self._handled = False
            self._reported_unclear = False
        self._previous = small

        event = None
        if self._is_still(now) and not self._handled and now >= self._next_try:
            event = self._interpret(board, warped)
            if event is not None and event.kind == "unclear":
                # Not a move we can name yet: keep re-reading a still picture, but only say so once.
                self._next_try = now + RETRY_SECONDS
                if self._reported_unclear:
                    event = None
                self._reported_unclear = True
            else:
                self._handled = True

        if self.headless:
            time.sleep(0.015)  # no windows, no keys: an app UI drives everything
            return event

        self._show(frame, warped, board)
        key = self._key(15 if self.screen is not None else 1)
        if key in (ord("q"), 27):
            return CameraEvent("quit")
        if key in (ord("r"), ord("R")):
            self.setup(board)  # on cancel the previous calibration stays in place
        if key in (ord("l"), ord("L")):
            return CameraEvent("unclear", message=self.relearn(board))
        if key in (ord("m"), ord("M")):
            return CameraEvent("toggle_mute")
        if key in (ord("s"), ord("S")):
            self.subtitles_on = not self.subtitles_on
        if key in (ord("h"), ord("H")):
            return CameraEvent("hint")
        if key in (ord("n"), ord("N")):
            return CameraEvent("new_game")
        if key in (ord("a"), ord("A")):
            self.arrows_on = not self.arrows_on
            self._refresh_overlay()
        return event

    def _is_still(self, now: float | None = None) -> bool:
        if self._still < STILL_FRAMES:
            return False
        if self.screen is None:
            return True
        return (time.monotonic() if now is None else now) - self._still_since >= STILL_SECONDS

    def _interpret(self, board: chess.Board, warped: np.ndarray) -> CameraEvent | None:
        observed = self.reader.read(warped, empty_hint=expected_grid(board, self.user_color) == 0)
        self._last_grid = observed
        moves, first = infer_moves(board, observed, self.user_color)
        if moves:
            return CameraEvent("moves", moves=moves, grid=observed)
        if first.status == "unchanged":
            return None
        if board.move_stack and np.array_equal(observed, expected_grid(chess.Board(), self.user_color)):
            return CameraEvent(
                "unclear",
                message="The board is back at the starting position. Is this a new game? Press N in the window (or type 'new').",
                grid=observed,
            )
        where = ", ".join(first.mismatches[:6]) or "?"
        return CameraEvent(
            "unclear",
            message=f"I couldn't tell what move was played (unsure around: {where}). Please type it.",
            grid=observed,
        )

    def _show(self, frame: np.ndarray, warped: np.ndarray, board: chess.Board) -> None:
        ready = self._is_still()
        state = "watching the board" if ready else "waiting for the board to be still"
        keys = [
            "Q quit  R recalibrate  L re-learn",
            f"N new game  H hint  S subtitles {'off' if self.subtitles_on else 'on'}  A arrow",
            f"M {self._mute_label()}",
        ]
        if self.screen is None:
            view = self.calibration.draw(frame, (0, 255, 0) if ready else (0, 165, 255))
            self._draw_arrow(view, self.calibration.to_frame)
            put_text(view, [self.status, state, *keys])
            self._draw_subtitle(view)
            self._present(view)

        board_view = warped.copy()
        for i in range(1, 8):
            cv2.line(board_view, (i * SQUARE_SIZE, 0), (i * SQUARE_SIZE, WARP_SIZE), (0, 255, 0), 1)
            cv2.line(board_view, (0, i * SQUARE_SIZE), (WARP_SIZE, i * SQUARE_SIZE), (0, 255, 0), 1)
        if self._last_grid is not None:
            for row in range(8):
                for col in range(8):
                    value = int(self._last_grid[row, col])
                    if value == 0:
                        continue
                    center = (col * SQUARE_SIZE + 10, row * SQUARE_SIZE + 10)
                    cv2.circle(board_view, center, 6, (255, 255, 255) if value == WHITE else (0, 0, 0), -1)
                    cv2.circle(board_view, center, 6, (0, 0, 255), 1)
        if self.screen is None:
            cv2.imshow(BOARD_WINDOW, board_view)
            return
        # One small status window, parked away from the captured area so it never covers the board.
        self._draw_arrow(board_view, lambda x, y: (int(x), int(y)))
        parts = [np.zeros((HEADER_HEIGHT, WARP_SIZE, 3), np.uint8), board_view]
        if self._caption():
            parts.append(np.zeros((SUBTITLE_HEIGHT, WARP_SIZE, 3), np.uint8))
        canvas = np.vstack(parts)
        put_text(canvas, [self.status, state, *keys])
        self._draw_subtitle(canvas)
        self._present(canvas)


def _max_square_change(current: np.ndarray, previous: np.ndarray) -> float:
    """Largest mean gray change in any of the 64 squares (a single piece move shows up clearly)."""
    diff = np.abs(current - previous).reshape(8, 8, 8, 8)
    return float(diff.mean(axis=(1, 3)).max())


def _standalone(args: argparse.Namespace) -> None:
    user_color = chess.WHITE if args.color == "white" else chess.BLACK
    session = CameraSession(user_color, args.camera, args.screen)
    board = chess.Board()
    try:
        session.open()
        if not session.setup(board):
            return
        print("Watching the board. Make moves on the physical board (Q in the window quits).")
        while True:
            event = session.step(board)
            if event is None:
                continue
            if event.kind == "quit":
                return
            if event.kind in ("toggle_mute", "hint", "new_game"):
                continue  # only meaningful inside the full program
            if event.grid is not None:
                print(grid_to_text(event.grid))
            if event.kind == "moves":
                for move in event.moves:
                    print("Saw move:", board.san(move))
                    board.push(move)
            else:
                print(event.message)
            print()
    except KeyboardInterrupt:
        pass
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Camera board-reading test.")
    parser.add_argument("--color", choices=["white", "black"], default="white")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--screen", nargs="?", const=1, type=int, metavar="MONITOR",
                        help="read the board from the screen instead of a webcam (default monitor 1)")
    _standalone(parser.parse_args())
