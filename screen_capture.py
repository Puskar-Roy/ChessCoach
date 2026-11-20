"""Screen capture that behaves like cv2.VideoCapture, so a shared screen / chess website can be
read by the same pipeline as a webcam.

Run this file directly to check what gets captured:
    python screen_capture.py --monitor 1
"""

import argparse
import threading
import time

import cv2
import mss
import numpy as np

REGION_WINDOW = "Select the board area"
MAX_PICK_WIDTH = 1400  # downscale big screens while the user draws the board rectangle


class ScreenCaptureError(RuntimeError):
    pass


class ScreenCapture:
    """Grabs frames (BGR) from one monitor, optionally cropped to a region.

    Safe to create on one thread and read on another: mss keeps Windows handles per thread, so every
    thread that reads gets its own grabber."""

    def __init__(self, monitor: int = 1):
        _make_dpi_aware()  # every window and capture then uses real screen pixels
        self._local = threading.local()
        self._grabbers: list = []
        self._closed = False
        monitors = self._grabber().monitors  # [0] is every screen together, [1:] are the real monitors
        if not 1 <= monitor < len(monitors):
            self.release()
            raise ScreenCaptureError(
                f"Monitor {monitor} does not exist (found {len(monitors) - 1}: use 1 to {len(monitors) - 1})."
            )
        self.monitor = monitor
        self._area = dict(monitors[monitor])
        self._region = dict(self._area)

    def _grabber(self):
        """The screen grabber of the calling thread (created on first use)."""
        sct = getattr(self._local, "sct", None)
        if sct is None:
            if self._closed:
                raise ScreenCaptureError("The screen capture is closed.")
            sct = mss.MSS()
            self._local.sct = sct
            self._grabbers.append(sct)
        return sct

    @property
    def monitor_left(self) -> int:
        return self._area["left"]

    @property
    def monitor_top(self) -> int:
        return self._area["top"]

    def read_monitor(self) -> np.ndarray:
        """The whole monitor as a BGR picture (for finding the board again)."""
        shot = self._grabber().grab(self._area)
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    @property
    def region(self) -> dict:
        """Captured rectangle in screen pixels: left, top, width, height."""
        return dict(self._region)

    def isOpened(self) -> bool:
        return not self._closed

    def set_region(self, x: int, y: int, width: int, height: int) -> None:
        """Crop to a rectangle given in pixels relative to the monitor's top-left corner."""
        self._region = {
            "left": self._area["left"] + x,
            "top": self._area["top"] + y,
            "width": width,
            "height": height,
        }

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._closed:
            return False, None
        try:
            shot = self._grabber().grab(self._region)
        except mss.exception.ScreenShotError:
            return False, None
        return True, np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def grab(self) -> bool:
        return True  # a screen has no stale buffered frames

    def release(self) -> None:
        self._closed = True
        for sct in self._grabbers:
            try:
                sct.close()
            except Exception:
                pass  # a grabber of a thread that already ended
        self._grabbers.clear()
        self._local = threading.local()

    def free_spot(self, width: int, height: int) -> tuple[int, int]:
        """Top-left screen position for a window of this size on the side of the monitor away from the region."""
        area, region = self._area, self._region
        space_left = region["left"] - area["left"]
        space_right = area["left"] + area["width"] - (region["left"] + region["width"])
        x = area["left"] + area["width"] - width if space_right >= space_left else area["left"]
        return max(x, area["left"]), area["top"] + 40

    def _snapshot(self, seconds: int, progress=print) -> np.ndarray:
        """Screenshot after a countdown, so the user can bring the chess board in front of this terminal."""
        self.set_region(0, 0, self._area["width"], self._area["height"])
        for left in range(seconds, 0, -1):
            progress(f"Taking a screenshot in {left}... bring the chess board into view")
            time.sleep(1)
        ok, screen = self.read()
        if not ok:
            raise ScreenCaptureError("Could not capture the screen.")
        return screen

    def select_region(self, countdown: int = 5, progress=print) -> bool:
        """Let the user drag a rectangle around the chess board. Returns False if cancelled.

        ENTER accepts, R resets the rectangle, T retakes the screenshot, ESC or Q cancels."""
        screen = self._snapshot(countdown, progress)
        # On the primary monitor the picker goes fullscreen at 1:1, so it lines up exactly with the real screen.
        fullscreen = self._area["left"] == 0 and self._area["top"] == 0
        scale = 1.0 if fullscreen else min(1.0, MAX_PICK_WIDTH / screen.shape[1])

        def fit(image):
            return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image

        shown = fit(screen)
        drag = {"start": None, "end": None, "down": False}

        def on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                drag.update(start=(x, y), end=(x, y), down=True)
            elif event == cv2.EVENT_MOUSEMOVE and drag["down"]:
                drag["end"] = (x, y)
            elif event == cv2.EVENT_LBUTTONUP and drag["down"]:
                drag.update(end=(x, y), down=False)

        def open_window():
            cv2.namedWindow(REGION_WINDOW, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(REGION_WINDOW, cv2.WND_PROP_TOPMOST, 1)  # otherwise it opens behind the browser
            if fullscreen:
                cv2.setWindowProperty(REGION_WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            else:
                cv2.moveWindow(REGION_WINDOW, 0, 0)
            cv2.setMouseCallback(REGION_WINDOW, on_mouse)

        def close_window():
            try:
                cv2.destroyWindow(REGION_WINDOW)
            except cv2.error:
                pass  # already closed with the X button

        open_window()
        try:
            while True:
                view = shown.copy()
                box = _box(drag["start"], drag["end"])
                if box is not None:
                    cv2.rectangle(view, box[:2], (box[0] + box[2], box[1] + box[3]), (0, 0, 255), 2)
                _label(view, "Drag a rectangle around the chess board.  ENTER = accept  R = reset  "
                             "T = retake screenshot  ESC = cancel")
                cv2.imshow(REGION_WINDOW, view)
                key = cv2.waitKey(30) & 0xFF
                if key in (27, ord("q"), ord("Q")) or window_gone(REGION_WINDOW):
                    return False
                if key in (ord("r"), ord("R")):
                    drag.update(start=None, end=None, down=False)
                if key in (ord("t"), ord("T")):
                    close_window()
                    shown = fit(self._snapshot(countdown, progress))
                    drag.update(start=None, end=None, down=False)
                    open_window()
                if key in (13, 10) and box is not None and box[2] >= 16 and box[3] >= 16:
                    x, y, w, h = (int(v / scale) for v in box)
                    board = find_board(screen, (x, y, w, h))
                    if board is not None:
                        progress(f"Board found on screen at x={board[0]}, y={board[1]}, {board[2]}x{board[2]} px.")
                        self.set_region(board[0], board[1], board[2], board[2])
                    else:
                        progress("Could not find the exact grid lines; using your rectangle as it is.")
                        self.set_region(x, y, w, h)
                    return True
        finally:
            close_window()


def find_board(screen: np.ndarray, rect: tuple[int, int, int, int]) -> tuple[int, int, int] | None:
    """Snap a rough rectangle around a chess board to the exact 8x8 grid on screen.

    Looks for the 9 evenly spaced lines (square borders) in the picture's edge profile. Works even if the
    rectangle cut off a row or left a margin. Returns (x, y, size) of the board, or None if no clear grid."""
    x, y, w, h = rect
    height, width = screen.shape[:2]
    s0 = min(w, h) / 8
    if s0 < 8:
        return None
    pad = int(s0 * 1.2)
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(width, x + w + pad), min(height, y + h + pad)
    gray = cv2.GaussianBlur(cv2.cvtColor(screen[top:bottom, left:right], cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.float32)
    # Square borders show up as columns/rows with lots of edge energy; use the part of the crop the user outlined.
    rows = slice(max(0, y - top), max(0, y - top) + h)
    cols = slice(max(0, x - left), max(0, x - left) + w)
    profile_x = np.abs(np.diff(gray[rows, :], axis=1)).sum(axis=0)
    profile_y = np.abs(np.diff(gray[:, cols], axis=0)).sum(axis=1)

    def refine(profile, start, size):
        """Place each of the 9 lines at its own edge-energy peak, then fit a straight line through them (sub-pixel)."""
        positions, indices = [], []
        for k in range(9):
            centre = int(round(start + k * size))
            lo, hi = max(0, centre - 2), min(len(profile), centre + 3)
            if hi - lo < 3:
                continue
            window = profile[lo:hi]
            j = int(window.argmax())
            offset = 0.0
            if 0 < j < len(window) - 1:  # parabola through the peak and its neighbours
                a, b, c = window[j - 1], window[j], window[j + 1]
                denominator = a - 2 * b + c
                offset = 0.5 * (a - c) / denominator if denominator else 0.0
            positions.append(lo + j + offset)
            indices.append(k)
        if len(positions) < 7:
            return start, size
        slope, intercept = np.polyfit(indices, positions, 1)
        residual = np.abs(np.array(positions) - (intercept + slope * np.array(indices)))
        keep = residual < 1.5
        if keep.sum() >= 6:
            slope, intercept = np.polyfit(np.array(indices)[keep], np.array(positions)[keep], 1)
        return float(intercept), float(slope)

    def best_grid(profile):
        # profile is smoothed by taking the max within +-1px so a border that falls between pixels still counts
        peaks = np.maximum(np.maximum(profile, np.roll(profile, 1)), np.roll(profile, -1))
        best = (-1.0, 0.0, 0.0)
        for size in np.arange(0.8 * s0, 1.25 * s0, 0.25):
            offsets = np.round(np.arange(9) * size).astype(int)
            span = offsets[-1]
            starts = np.arange(0, len(profile) - span - 1)
            if len(starts) == 0:
                continue
            score = peaks[starts[:, None] + offsets[None, :]].sum(axis=1)
            i = int(score.argmax())
            if score[i] > best[0]:
                best = (float(score[i]), float(starts[i]), float(size))
        if best[0] < 0:
            return best
        start, size = refine(profile, best[1], best[2])
        return best[0], start, size

    score_x, start_x, size_x = best_grid(profile_x)
    score_y, start_y, size_y = best_grid(profile_y)
    if score_x < 0 or score_y < 0 or abs(size_x - size_y) > 0.03 * size_x:
        return None
    size = int(round(8 * (size_x + size_y) / 2))
    return left + int(round(start_x + 0.5)), top + int(round(start_y + 0.5)), size


def _make_dpi_aware() -> None:
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def hide_from_capture(title: str) -> bool:
    """Make a window invisible to screen capture (Windows 10 2004+), so our own preview cannot be
    captured back into the board image. Returns False if that is not possible."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        root = user32.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT: OpenCV draws in a child of the real window
        return bool(root and user32.SetWindowDisplayAffinity(root, 0x11))  # WDA_EXCLUDEFROMCAPTURE
    except (AttributeError, OSError):
        return False


def exclude_from_capture(hwnd: int, on: bool = True) -> bool:
    """Hide (or show again) a window, by handle, from screen capture. Windows 10 2004+."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        root = user32.GetAncestor(hwnd, 2) or hwnd
        return bool(user32.SetWindowDisplayAffinity(root, 0x11 if on else 0))
    except (AttributeError, OSError):
        return False


def focus_window(title: str) -> None:
    """Best effort: give keyboard focus to our window so its keys work right after it appears."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.SetForegroundWindow(user32.GetAncestor(hwnd, 2))
    except (AttributeError, OSError):
        pass


def window_gone(title: str) -> bool:
    """True once the user has closed the window with its X button."""
    return cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1


def _box(start, end) -> tuple[int, int, int, int] | None:
    if start is None or end is None:
        return None
    return min(start[0], end[0]), min(start[1], end[1]), abs(end[0] - start[0]), abs(end[1] - start[1])


def _label(image: np.ndarray, text: str) -> None:
    cv2.rectangle(image, (0, 0), (image.shape[1], 44), (0, 0, 0), -1)
    cv2.putText(image, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(image, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)


def _standalone(args: argparse.Namespace) -> None:
    capture = ScreenCapture(args.monitor)
    try:
        print("Drag a rectangle around the board, then press ENTER (ESC to cancel).")
        if not capture.select_region():
            return
        print("Showing the captured area. Press Q or ESC in the window to quit.")
        while True:
            ok, frame = capture.read()
            if not ok:
                return
            cv2.imshow("Screen capture", frame)
            if cv2.waitKey(30) & 0xFF in (ord("q"), 27):
                return
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Screen capture test.")
    parser.add_argument("--monitor", type=int, default=1)
    _standalone(parser.parse_args())
