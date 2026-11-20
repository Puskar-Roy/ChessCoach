"""Per-square classification of a flat (warped) board image: empty / white piece / black piece.

Classical CV only. The reader *learns* from a position whose pieces are known (the start position,
or the current game position), so it adapts to the user's board, pieces and lighting:

  1. Fit a model of what an EMPTY light square and an EMPTY dark square look like at every spot on
     the board (colour as a linear function of position, which absorbs lighting gradients).
  2. For every square describe how its centre differs from that empty model: share of changed
     pixels, edge density, brightness shift, colour shift, texture.
  3. Train a tiny softmax classifier (empty / white / black) on those descriptions.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from calibration import SQUARE_SIZE

EMPTY, WHITE, BLACK = 0, 1, 2
FEATURE_COUNT = 9
AUGMENT_ROUNDS = 6  # extra training copies with random highlights / move dots painted on squares
MIN_STD = 0.1  # floor for feature scaling so a constant training feature cannot explode later

_lo, _hi = int(SQUARE_SIZE * 0.25), int(SQUARE_SIZE * 0.75)
CENTER_MASK = np.zeros((SQUARE_SIZE, SQUARE_SIZE), dtype=bool)
CENTER_MASK[_lo:_hi, _lo:_hi] = True


class NotCalibrated(RuntimeError):
    pass


@dataclass(frozen=True)
class LearnReport:
    errors: int  # squares misread when re-reading the image it learned from
    occupied: int
    empty: int
    bad_cells: tuple[tuple[int, int], ...] = ()  # (row, col) of those squares, image orientation


@dataclass
class _Model:
    empty_coeffs: dict[int, np.ndarray]  # square-colour parity -> (3, 3) coefficients for [1, row, col]
    mean: np.ndarray
    std: np.ndarray
    weights: np.ndarray  # (FEATURE_COUNT + 1, 3)

    def empty_color(self, row: int, col: int) -> np.ndarray:
        return np.array([1.0, row, col]) @ self.empty_coeffs[(row + col) % 2]


def _lab_and_edges(warped: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    blurred = cv2.GaussianBlur(warped, (5, 5), 0)
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    return lab, cv2.Canny(gray, 40, 120) > 0


def _center(lab: np.ndarray, row: int, col: int) -> np.ndarray:
    y, x = row * SQUARE_SIZE, col * SQUARE_SIZE
    return lab[y : y + SQUARE_SIZE, x : x + SQUARE_SIZE][CENTER_MASK]


def _fit_empty_model(lab: np.ndarray, expected: np.ndarray) -> dict[int, np.ndarray]:
    coeffs = {}
    for parity in (0, 1):
        rows, colors = [], []
        for r in range(8):
            for c in range(8):
                if expected[r, c] == EMPTY and (r + c) % 2 == parity:
                    rows.append([1.0, r, c])
                    colors.append(np.median(_center(lab, r, c), axis=0))
        if not rows:
            raise ValueError("Need some empty squares of both square colours to learn from.")
        if len(rows) >= 6:
            fitted = np.linalg.lstsq(np.array(rows), np.array(colors), rcond=None)[0]
        else:  # too few to fit a gradient: use a flat colour
            fitted = np.zeros((3, 3))
            fitted[0] = np.mean(colors, axis=0)
        coeffs[parity] = fitted
    return coeffs


def _features(lab: np.ndarray, edges: np.ndarray, empty_color) -> np.ndarray:
    out = np.zeros((8, 8, FEATURE_COUNT), dtype=np.float64)
    for r in range(8):
        for c in range(8):
            pixels = _center(lab, r, c)
            diff = pixels - empty_color(r, c)
            distance = np.linalg.norm(diff, axis=1)
            d_lightness = diff[:, 0]
            y, x = r * SQUARE_SIZE, c * SQUARE_SIZE
            edge_density = edges[y : y + SQUARE_SIZE, x : x + SQUARE_SIZE][CENTER_MASK].mean()
            out[r, c] = (
                (distance > 25).mean(),
                (distance > 40).mean(),
                edge_density * 10,
                d_lightness.mean() / 50,
                np.abs(d_lightness).mean() / 50,
                np.linalg.norm(diff[:, 1:], axis=1).mean() / 30,
                pixels[:, 0].std() / 30,
                (d_lightness < -40).mean(),
                (d_lightness > 25).mean(),
            )
    return out


def _paint_overlays(warped: np.ndarray, expected: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Copy of the image with random square highlights and move-hint dots, like chess websites draw
    (last-move squares, selected piece, legal-move dots, premove marks). Labels are unaffected."""
    out = warped.astype(np.float32)
    for r in range(8):
        for c in range(8):
            y, x = r * SQUARE_SIZE, c * SQUARE_SIZE
            if rng.random() < 0.3:
                if rng.random() < 0.6:  # yellow / lime, the usual "last move" colours
                    color = np.array([rng.uniform(0, 120), rng.uniform(150, 255), rng.uniform(100, 255)])
                else:
                    color = rng.uniform(0, 255, 3)
                alpha = rng.uniform(0.35, 0.8)
                out[y : y + SQUARE_SIZE, x : x + SQUARE_SIZE] = (
                    (1 - alpha) * out[y : y + SQUARE_SIZE, x : x + SQUARE_SIZE] + alpha * color
                )
            if expected[r, c] == EMPTY and rng.random() < 0.15:  # legal-move dot
                patch = np.zeros((SQUARE_SIZE, SQUARE_SIZE), dtype=np.uint8)
                cv2.circle(patch, (SQUARE_SIZE // 2, SQUARE_SIZE // 2), int(SQUARE_SIZE * rng.uniform(0.12, 0.2)), 1, -1)
                shade = rng.uniform(0.6, 0.95) if rng.random() < 0.7 else rng.uniform(1.05, 1.25)
                region = out[y : y + SQUARE_SIZE, x : x + SQUARE_SIZE]
                region[patch == 1] *= shade
    return np.clip(out, 0, 255).astype(np.uint8)


def _train_softmax(x: np.ndarray, y: np.ndarray, l2: float = 0.001, steps: int = 3000, rate: float = 0.5):
    mean = x.mean(axis=0)
    std = np.maximum(x.std(axis=0), MIN_STD)
    z = np.hstack([(x - mean) / std, np.ones((len(x), 1))])
    onehot = np.eye(3)[y]
    weights = np.zeros((z.shape[1], 3))
    for _ in range(steps):
        logits = z @ weights
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        gradient = z.T @ (probs - onehot) / len(z)
        gradient[:-1] += l2 * weights[:-1]
        weights -= rate * gradient
    return mean, std, weights


def _predict(model: _Model, features: np.ndarray) -> np.ndarray:
    z = np.hstack([(features - model.mean) / model.std, np.ones((len(features), 1))])
    return (z @ model.weights).argmax(axis=1)


class BoardReader:
    def __init__(self, augment: bool = False):
        """`augment` trains against highlighted squares and move dots too (needed for on-screen boards)."""
        self.augment = augment
        self._model: _Model | None = None

    @property
    def calibrated(self) -> bool:
        return self._model is not None

    def learn(self, warped: np.ndarray, expected: np.ndarray) -> LearnReport:
        """Learn from an image of a known position.

        `expected` is an 8x8 array (image orientation) of EMPTY/WHITE/BLACK."""
        labels = expected.reshape(64).astype(int)
        occupied = int((labels != EMPTY).sum())
        if occupied < 4 or 64 - occupied < 4:
            raise ValueError("Need at least 4 empty and 4 occupied squares to learn from.")
        if not (labels == WHITE).any() or not (labels == BLACK).any():
            raise ValueError("Need pieces of both colors on the board to learn from.")

        lab, edges = _lab_and_edges(warped)
        white_light = np.mean([_center(lab, r, c)[:, 0].mean() for r, c in np.argwhere(expected == WHITE)])
        black_light = np.mean([_center(lab, r, c)[:, 0].mean() for r, c in np.argwhere(expected == BLACK)])
        if white_light < black_light:
            raise ValueError(
                "The pieces expected to be WHITE look darker than the black ones. Is the board flipped, "
                "or are you playing the other colour? Show the board from your side (use --color)."
            )
        coeffs = _fit_empty_model(lab, expected)
        probe = _Model(coeffs, np.zeros(FEATURE_COUNT), np.ones(FEATURE_COUNT), np.zeros((FEATURE_COUNT + 1, 3)))
        features = _features(lab, edges, probe.empty_color).reshape(64, FEATURE_COUNT)
        train_x, train_y = [features], [labels]
        if self.augment:
            rng = np.random.default_rng(0)
            for _ in range(AUGMENT_ROUNDS):
                painted_lab, painted_edges = _lab_and_edges(_paint_overlays(warped, expected, rng))
                train_x.append(_features(painted_lab, painted_edges, probe.empty_color).reshape(64, FEATURE_COUNT))
                train_y.append(labels)
        mean, std, weights = _train_softmax(np.vstack(train_x), np.concatenate(train_y))
        self._model = _Model(coeffs, mean, std, weights)

        wrong = _predict(self._model, features) != labels
        bad = tuple((int(i) // 8, int(i) % 8) for i in np.flatnonzero(wrong))
        return LearnReport(errors=len(bad), occupied=occupied, empty=64 - occupied, bad_cells=bad)

    def read(self, warped: np.ndarray, empty_hint: np.ndarray | None = None) -> np.ndarray:
        """Classify every square.

        `empty_hint` is an optional 8x8 boolean array of squares believed to be empty right now
        (e.g. from the position before the move). They re-anchor the empty-square colours to this
        frame's exposure, which webcams change on their own."""
        if self._model is None:
            raise NotCalibrated("Reader has not learned from a known position yet.")
        lab, edges = _lab_and_edges(warped)
        empty_color = self._model.empty_color
        if empty_hint is not None:
            empty_color = self._reanchored(lab, empty_hint)
        features = _features(lab, edges, empty_color).reshape(64, FEATURE_COUNT)
        return _predict(self._model, features).reshape(8, 8).astype(np.int8)

    def _reanchored(self, lab: np.ndarray, empty_hint: np.ndarray):
        """Empty-colour function shifted by the median drift seen on squares believed empty."""
        model = self._model
        offsets = {}
        for parity in (0, 1):
            drifts = [
                np.median(_center(lab, r, c), axis=0) - model.empty_color(r, c)
                for r in range(8)
                for c in range(8)
                if empty_hint[r, c] and (r + c) % 2 == parity
            ]
            offsets[parity] = np.median(drifts, axis=0) if len(drifts) >= 4 else np.zeros(3)
        return lambda r, c: model.empty_color(r, c) + offsets[(r + c) % 2]


def grid_to_text(grid: np.ndarray) -> str:
    symbols = {EMPTY: ".", WHITE: "W", BLACK: "b"}
    return "\n".join(" ".join(symbols[int(v)] for v in row) for row in grid)
