"""Recognise which chess piece stands on a square of an on-screen board.

The silhouette of a piece (cut out against its own square) and the lines inside it are turned into a
small feature vector; a small neural network, trained on many different piece sets drawn on many
different board colours (`tools/train_pieces.py`), turns that into a probability for each of
pawn / knight / bishop / rook / queen / king. The picture is colour-free on purpose, so a white and a
black piece of the same kind look alike to it.
"""

from pathlib import Path

import cv2
import numpy as np

from calibration import SQUARE_SIZE

KINDS = "pnbrqk"
MODEL_PATH = Path(__file__).parent / "models" / "pieces.npz"
GRID = 24


def silhouette(cell_lab: np.ndarray) -> np.ndarray:
    """Foreground mask of one square: pixels that differ from the square's own background ring."""
    s = cell_lab.shape[0]
    inner, outer = int(s * 0.05), max(int(s * 0.13), int(s * 0.05) + 2)
    mid = slice(int(s * 0.3), int(s * 0.7))
    strips = [cell_lab[inner:outer, mid], cell_lab[s - outer : s - inner, mid], cell_lab[mid, inner:outer], cell_lab[mid, s - outer : s - inner]]
    background = np.median(np.concatenate([strip.reshape(-1, 3) for strip in strips]), axis=0)
    distance = np.linalg.norm(cell_lab - background, axis=2)
    mask = (distance > 22).astype(np.uint8)
    margin = int(s * 0.06)
    mask[:margin] = mask[-margin:] = 0
    mask[:, :margin] = mask[:, -margin:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count > 1:  # keep the biggest blob: the piece (drops coordinate letters, dots, rings)
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (labels == biggest).astype(np.uint8)
    return mask


def _letterbox(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """The part of `image` inside `box`, scaled to GRID x GRID without changing its proportions."""
    x0, y0, x1, y1 = box
    crop = image[y0:y1, x0:x1].astype(np.float32)
    h, w = crop.shape
    side = max(h, w)
    canvas = np.zeros((side, side), np.float32)
    canvas[(side - h) // 2 : (side - h) // 2 + h, (side - w) // 2 : (side - w) // 2 + w] = crop
    return cv2.resize(canvas, (GRID, GRID), interpolation=cv2.INTER_AREA)


def cell_vector(cell_bgr: np.ndarray) -> np.ndarray | None:
    """Feature vector of one square picture (any size, it is resized to SQUARE_SIZE), None if empty."""
    if cell_bgr.shape[0] != SQUARE_SIZE:
        cell_bgr = cv2.resize(cell_bgr, (SQUARE_SIZE, SQUARE_SIZE), interpolation=cv2.INTER_AREA)
    blurred = cv2.GaussianBlur(cell_bgr, (3, 3), 0)
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB).astype(np.float32)
    mask = silhouette(lab)
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    inside = cv2.erode(mask, np.ones((3, 3), np.uint8))
    relief = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F, ksize=3)
    lines = (np.abs(relief) * inside)
    lines = lines / max(float(lines.max()), 1e-6)
    shape_box = _letterbox(mask, (x0, y0, x1, y1))
    detail_box = _letterbox(lines, (x0, y0, x1, y1))
    placed = cv2.resize(mask.astype(np.float32), (12, 12), interpolation=cv2.INTER_AREA)  # size and position
    width, height = (x1 - x0) / SQUARE_SIZE, (y1 - y0) / SQUARE_SIZE
    widths = mask[y0:y1, x0:x1].sum(axis=1).astype(np.float32)
    profile = cv2.resize(widths.reshape(-1, 1), (1, 12), interpolation=cv2.INTER_AREA).ravel() / max(widths.max(), 1.0)
    stats = np.array([width, height, width / max(height, 1e-6), float(mask.mean()), (x0 + x1) / 2 / SQUARE_SIZE, y1 / SQUARE_SIZE], np.float32)
    return np.concatenate([shape_box.ravel(), detail_box.ravel(), placed.ravel(), profile, stats, _tones(lab, mask)]).astype(np.float32)


def _tones(lab: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """How light the piece is: inside, along its outline, and against its own square (tells white from black)."""
    lightness = lab[:, :, 0]
    s = lab.shape[0]
    ring = np.concatenate([lightness[3:8, 18:42].ravel(), lightness[s - 8 : s - 3, 18:42].ravel(), lightness[18:42, 3:8].ravel(), lightness[18:42, s - 8 : s - 3].ravel()])
    background = float(np.median(ring))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 1, -1)
    body = cv2.erode(filled, np.ones((5, 5), np.uint8))
    if body.sum() < 25:
        body = filled if filled.sum() else mask
    edge = (filled > 0) & (cv2.erode(filled, np.ones((5, 5), np.uint8)) == 0)
    def histogram(selection):
        values = lightness[selection > 0] if selection.dtype != bool else lightness[selection]
        if values.size == 0:
            return np.zeros(8, np.float32)
        return (np.histogram(values, bins=8, range=(0, 255))[0] / values.size).astype(np.float32)
    body_values = lightness[body > 0]
    summary = np.array([background / 255, (np.median(body_values) - background) / 255 if body_values.size else 0, np.median(body_values) / 255 if body_values.size else 0,
                        np.percentile(body_values, 25) / 255 if body_values.size else 0, np.percentile(body_values, 75) / 255 if body_values.size else 0], np.float32)
    return np.concatenate([histogram(body), histogram(edge), summary])


class PieceModel:
    """A small fully connected network: features -> probability of each kind."""

    def __init__(self, weights: dict[str, np.ndarray]):
        self.mean, self.scale = weights["mean"], weights["scale"]
        self.layers = [(weights[f"w{i}"], weights[f"b{i}"]) for i in range(len([k for k in weights if k.startswith("w")]))]

    @staticmethod
    def load(path: Path = MODEL_PATH) -> "PieceModel | None":
        if not Path(path).exists():
            return None
        with np.load(path) as data:
            return PieceModel({k: data[k] for k in data.files})

    def probabilities(self, vectors: np.ndarray) -> np.ndarray:
        """(n, 12): probability of every white (0-5) and black (6-11) kind."""
        x = (vectors - self.mean) / self.scale
        for index, (w, b) in enumerate(self.layers):
            x = x @ w + b
            if index < len(self.layers) - 1:
                x = np.maximum(x, 0)
        x = x - x.max(axis=1, keepdims=True)
        e = np.exp(x)
        return e / e.sum(axis=1, keepdims=True)


_model: "PieceModel | None | bool" = False


def get_model() -> "PieceModel | None":
    global _model
    if _model is False:
        _model = PieceModel.load()
    return _model


def classify_squares(warped: np.ndarray, squares: list[int]) -> dict[int, np.ndarray]:
    """{square index: probabilities over KINDS} for the given squares of a warped board picture."""
    model = get_model()
    if model is None:
        return {}
    vectors, kept = [], []
    for index in squares:
        r, c = divmod(index, 8)
        vector = cell_vector(warped[r * SQUARE_SIZE : (r + 1) * SQUARE_SIZE, c * SQUARE_SIZE : (c + 1) * SQUARE_SIZE])
        if vector is not None:
            vectors.append(vector)
            kept.append(index)
    if not vectors:
        return {}
    probabilities = model.probabilities(np.stack(vectors))
    return {index: p for index, p in zip(kept, probabilities)}


def split_colour(p: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """(chance the piece is white, kinds if white, kinds if black) from the 12 probabilities."""
    white, black = p[:6], p[6:]
    return float(white.sum()), white / max(white.sum(), 1e-9), black / max(black.sum(), 1e-9)
