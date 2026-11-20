"""Board calibration: pick the 4 board corners once, then warp camera frames to a flat top-down 8x8 grid.

The user clicks the corners in a fixed order (see CORNER_PROMPTS), so the camera can sit at any
angle: the warped image always has the user's side of the board at the bottom."""

import json
import math
from pathlib import Path

import cv2
import numpy as np

WARP_SIZE = 480
SQUARE_SIZE = WARP_SIZE // 8
CALIBRATION_FILE = Path(__file__).resolve().parent / "data" / "calibration.json"
WINDOW = "Chess camera"


def order_corners(points) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left (image coordinates)."""
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] != 4:
        raise ValueError("Need exactly 4 corner points.")
    center = pts.mean(axis=0)
    angles = [math.atan2(p[1] - center[1], p[0] - center[0]) for p in pts]
    ordered = pts[np.argsort(angles)]  # clockwise on screen, starting near top-left
    if len({(float(p[0]), float(p[1])) for p in ordered}) < 4:
        raise ValueError("Corner points must be distinct.")
    return ordered.astype(np.float32)


# Click order: as seen by the player sitting on their own side of the board.
CORNER_PROMPTS = {
    True: [("a1", "bottom-left"), ("h1", "bottom-right"), ("h8", "top-right"), ("a8", "top-left")],
    False: [("h8", "bottom-left"), ("a8", "bottom-right"), ("a1", "top-right"), ("h1", "top-left")],
}


class Calibration:
    def __init__(self, corners, ordered: bool = False):
        """`corners` as top-left, top-right, bottom-right, bottom-left if `ordered`, else any order."""
        self.corners = (
            np.asarray(corners, dtype=np.float32).reshape(4, 2) if ordered else order_corners(corners)
        )
        destination = np.float32(
            [[0, 0], [WARP_SIZE, 0], [WARP_SIZE, WARP_SIZE], [0, WARP_SIZE]]
        )
        self.matrix = cv2.getPerspectiveTransform(self.corners, destination)

    def warp(self, frame: np.ndarray) -> np.ndarray:
        return cv2.warpPerspective(frame, self.matrix, (WARP_SIZE, WARP_SIZE))

    def to_frame(self, x: float, y: float) -> tuple[int, int]:
        """Pixel in the camera/screen frame for a point (x, y) of the flat, warped board image."""
        return _project(np.linalg.inv(self.matrix), (x, y))

    def draw(self, frame: np.ndarray, color=(0, 255, 0)) -> np.ndarray:
        out = frame.copy()
        cv2.polylines(out, [self.corners.astype(np.int32)], True, color, 2)
        inverse = np.linalg.inv(self.matrix)
        for i in range(1, 8):
            for a, b in (((i * SQUARE_SIZE, 0), (i * SQUARE_SIZE, WARP_SIZE)),
                         ((0, i * SQUARE_SIZE), (WARP_SIZE, i * SQUARE_SIZE))):
                pa = _project(inverse, a)
                pb = _project(inverse, b)
                cv2.line(out, pa, pb, color, 1)
        return out

    def save(self, path: Path = CALIBRATION_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"corners": self.corners.tolist()}), encoding="utf-8")

    @classmethod
    def from_clicks(cls, clicks) -> "Calibration":
        """Clicks in player order: bottom-left, bottom-right, top-right, top-left."""
        bottom_left, bottom_right, top_right, top_left = clicks
        return cls([top_left, top_right, bottom_right, bottom_left], ordered=True)

    @classmethod
    def load(cls, path: Path = CALIBRATION_FILE) -> "Calibration | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data["corners"], ordered=True)
        except (OSError, ValueError, KeyError):
            return None


def _project(matrix: np.ndarray, point) -> tuple[int, int]:
    vector = matrix @ np.array([point[0], point[1], 1.0])
    return int(vector[0] / vector[2]), int(vector[1] / vector[2])


def put_text(image: np.ndarray, lines: list[str], color=(0, 255, 255)) -> None:
    """Draw instructions on a dark banner so they stay readable on any background (e.g. a white web page)."""
    lines = [line for line in lines if line]
    if not lines:
        return
    scale, thickness = 0.6, 1
    banner_height = 14 + 24 * len(lines)
    banner = image[:banner_height]
    banner[:] = (banner * 0.15).astype(np.uint8)  # darken, rather than cover, the top strip
    for i, line in enumerate(lines):
        y = 26 + i * 24
        cv2.putText(image, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness + 1, cv2.LINE_AA)


def wrap_text(text: str, width: int, scale: float = 0.6) -> list[str]:
    """Break text into lines that fit `width` pixels."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and cv2.getTextSize(trial, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def with_header(view: np.ndarray, lines: list[str]) -> tuple[np.ndarray, int]:
    """Put instructions in their own black strip above the picture, so no text covers the board.

    Returns (image, header_height)."""
    wrapped = [part for line in lines if line for part in wrap_text(line, view.shape[1] - 20)]
    header = np.zeros((14 + 24 * max(1, len(wrapped)), view.shape[1], 3), np.uint8)
    put_text(header, wrapped)
    return np.vstack([header, view]), header.shape[0]


def pick_corners(snapshot: np.ndarray, user_color: bool = True) -> list[tuple[int, int]] | None:
    """Let the user click the 4 outer corners of the 8x8 playing area on a still image.

    Clicks must be in player order (bottom-left, bottom-right, top-right, top-left as seen from the
    user's side of the board). Returns the clicks, or None if cancelled.
    ENTER accepts after 4 clicks, R resets, BACKSPACE undoes the last click, ESC cancels."""
    points: list[tuple[int, int]] = []
    prompts = CORNER_PROMPTS[user_color]
    offset = [0]  # height of the instruction strip above the picture

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4 and y >= offset[0]:
            points.append((x, y - offset[0]))

    cv2.setMouseCallback(WINDOW, on_mouse)
    try:
        while True:
            view = snapshot.copy()
            for i, p in enumerate(points):
                cv2.circle(view, p, 5, (0, 0, 255), -1)
                cv2.putText(view, str(i + 1), (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            if len(points) > 1:
                cv2.polylines(view, [np.array(points, dtype=np.int32)], len(points) == 4, (0, 255, 0), 1)
            if len(points) < 4:
                square, place = prompts[len(points)]
                instruction = f"Click corner {len(points) + 1}/4: {square} ({place} as YOU sit at the board)"
            else:
                instruction = "ENTER = accept"
            view, offset[0] = with_header(view, [instruction, "BACKSPACE = undo   R = reset   ESC = cancel"])
            cv2.imshow(WINDOW, view)
            key = cv2.waitKey(30) & 0xFF
            if key == 27 or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return None
            if key in (ord("r"), ord("R")):
                points.clear()
            if key == 8 and points:
                points.pop()
            if key in (13, 10) and len(points) == 4:
                return list(points)
    finally:
        cv2.setMouseCallback(WINDOW, lambda *args: None)
