"""Per-square classification of a flat, on-screen chess board: empty / white piece / black piece.

Websites decorate squares (last-move colours, selection, check glow, move dots, arrows, coordinates), so
nothing here compares a square with a fixed "empty" colour. Every square is judged against ITS OWN
background, measured on a thin ring just inside its border where pieces rarely reach:

  * is there a piece?  -> does the middle of the square differ from that ring, and does it have edges?
  * which colour?      -> how light is the middle of the square (a piece body), in absolute terms.

Two tiny logistic models (occupied / white-or-black) are trained from a position the program knows
(the start position) and keep improving during the game: every confirmed position is added as a new
training picture, so the reader learns the site's real highlights and piece art within a few moves.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from calibration import SQUARE_SIZE
from board_reader import BLACK, EMPTY, WHITE, LearnReport

OCCUPANCY_FEATURES = 12
COLOR_FEATURES = 6
MAX_MEMORY = 14  # positions kept for retraining
RING_INNER, RING_OUTER = 0.05, 0.13  # ring band as a share of the square size
CENTER = (0.22, 0.78)  # the middle of the square, where a piece body is
CORE = (0.38, 0.62)  # the very middle (colour of the piece body)
AUGMENT_ROUNDS = 5


@dataclass
class _Model:
    occ_mean: np.ndarray
    occ_std: np.ndarray
    occ_weights: np.ndarray
    col_mean: np.ndarray
    col_std: np.ndarray
    col_weights: np.ndarray


def _train_logistic(x: np.ndarray, y: np.ndarray, l2: float = 0.01, steps: int = 1500, rate: float = 0.8, start=None):
    """Logistic regression by gradient descent. `start` = (mean, std, weights) of a previous fit to continue from."""
    if start is not None:
        mean, std, weights = start
        weights = weights.copy()
    else:
        mean = x.mean(axis=0)
        std = np.maximum(x.std(axis=0), 0.05)
        weights = np.zeros(x.shape[1] + 1)
    z = np.hstack([(x - mean) / std, np.ones((len(x), 1))])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(z @ weights, -30, 30)))
        gradient = z.T @ (p - y) / len(z)
        gradient[:-1] += l2 * weights[:-1]
        weights -= rate * gradient
    return mean, std, weights


def _logistic(x: np.ndarray, mean, std, weights) -> np.ndarray:
    z = np.hstack([(x - mean) / std, np.ones((len(x), 1))])
    return 1 / (1 + np.exp(-np.clip(z @ weights, -30, 30)))


def _slice(size: int, low: float, high: float) -> slice:
    return slice(int(size * low), max(int(size * low) + 1, int(size * high)))


def cell_features(warped: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(occupancy features (64, 12), colour features (64, 6)) for a warped board image."""
    blurred = cv2.GaussianBlur(warped, (3, 3), 0)
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    edges = (cv2.Canny(gray, 30, 90) > 0).astype(np.float32)
    s = SQUARE_SIZE
    inner, outer = int(s * RING_INNER), max(int(s * RING_OUTER), int(s * RING_INNER) + 2)
    mid = _slice(s, 0.3, 0.7)  # edge strips use only the middle part of each side (labels live in corners)
    occupancy = np.zeros((64, OCCUPANCY_FEATURES), np.float32)
    color = np.zeros((64, COLOR_FEATURES), np.float32)
    for r in range(8):
        for c in range(8):
            y, x = r * s, c * s
            cell = lab[y : y + s, x : x + s]
            strips = [cell[inner:outer, mid], cell[s - outer : s - inner, mid], cell[mid, inner:outer], cell[mid, s - outer : s - inner]]
            ring = np.concatenate([strip.reshape(-1, 3) for strip in strips])
            background = np.median(ring, axis=0)
            ring_spread = float(np.median(np.linalg.norm(ring - background, axis=1)))
            rows, cols = _slice(s, *CENTER), _slice(s, *CENTER)
            center = cell[rows, cols].reshape(-1, 3)
            distance = np.linalg.norm(center - background, axis=1)
            lightness = center[:, 0]
            core = cell[_slice(s, *CORE), _slice(s, *CORE)].reshape(-1, 3)
            edge_density = float(edges[y : y + s, x : x + s][rows, cols].mean())
            foreground = lightness[distance > 18]
            occupancy[r * 8 + c] = (
                (distance > 18).mean(),
                (distance > 35).mean(),
                distance.mean() / 40,
                np.median(distance) / 40,
                edge_density * 8,
                lightness.std() / 30,
                np.abs(np.median(lightness) - background[0]) / 40,
                np.linalg.norm(core.mean(axis=0) - background) / 40,
                (lightness < background[0] - 25).mean(),
                (lightness > background[0] + 25).mean(),
                ring_spread / 20,
                center[:, 1:].std(axis=0).mean() / 20,
            )
            core_light = float(np.median(core[:, 0]))
            color[r * 8 + c] = (
                core_light / 100,
                (float(np.median(foreground)) if len(foreground) else core_light) / 100,
                float(np.percentile(lightness, 15)) / 100,
                float(np.percentile(lightness, 85)) / 100,
                (core_light - background[0]) / 60,
                float(core[:, 0].mean()) / 100,
            )
    return occupancy, color


def _paint_overlays(warped: np.ndarray, expected: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A copy with random highlights, move dots, rings and a user arrow, like chess websites draw."""
    out = warped.astype(np.float32)
    s = SQUARE_SIZE
    for r in range(8):
        for c in range(8):
            y, x = r * s, c * s
            if rng.random() < 0.3:
                color = np.array([rng.uniform(0, 120), rng.uniform(150, 255), rng.uniform(100, 255)]) if rng.random() < 0.6 else rng.uniform(0, 255, 3)
                alpha = rng.uniform(0.3, 0.7)
                out[y : y + s, x : x + s] = (1 - alpha) * out[y : y + s, x : x + s] + alpha * color
            if rng.random() < 0.12:
                patch = np.zeros((s, s), np.uint8)
                if expected[r, c] == EMPTY:
                    cv2.circle(patch, (s // 2, s // 2), int(s * rng.uniform(0.12, 0.2)), 1, -1)
                else:
                    cv2.circle(patch, (s // 2, s // 2), int(s * 0.46), 1, max(2, s // 14))
                out[y : y + s, x : x + s][patch == 1] *= rng.uniform(0.6, 0.9)
    if rng.random() < 0.5:
        overlay = out.copy()
        start = tuple(int(v) for v in rng.integers(0, 8 * s, 2))
        end = tuple(int(v) for v in rng.integers(0, 8 * s, 2))
        cv2.arrowedLine(overlay, start, end, (60, 170, 40), max(4, s // 6), cv2.LINE_AA, tipLength=0.3)
        out = 0.3 * out + 0.7 * overlay
    return np.clip(out, 0, 255).astype(np.uint8)


class ScreenReader:
    """Same interface as BoardReader (learn / read), tuned for boards drawn on a screen."""

    def __init__(self, augment: bool = True):
        self.augment = augment
        self._model: _Model | None = None
        self._base: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []  # the picture it was taught with (+ augmented copies)
        self._recent: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []  # confirmed game positions, newest last

    @property
    def calibrated(self) -> bool:
        return self._model is not None

    # ---- training
    def _examples(self, warped: np.ndarray, expected: np.ndarray):
        labels = expected.reshape(64).astype(int)
        occ, col = cell_features(warped)
        out = [(occ, col, labels)]
        if self.augment:
            rng = np.random.default_rng(len(self._recent) + 1)
            for _ in range(AUGMENT_ROUNDS):
                occ_a, col_a = cell_features(_paint_overlays(warped, expected, rng))
                out.append((occ_a, col_a, labels))
        return out

    def learn(self, warped: np.ndarray, expected: np.ndarray) -> LearnReport:
        """Learn from a picture of a known position. Resets what was learned before."""
        labels = expected.reshape(64).astype(int)
        occupied = int((labels != EMPTY).sum())
        if occupied < 4 or 64 - occupied < 4:
            raise ValueError("Need at least 4 empty and 4 occupied squares to learn from.")
        if not (labels == WHITE).any() or not (labels == BLACK).any():
            raise ValueError("Need pieces of both colors on the board to learn from.")
        probe_occ, probe_col = cell_features(warped)
        if probe_col[labels == WHITE, 0].mean() < probe_col[labels == BLACK, 0].mean():
            raise ValueError(
                "The pieces expected to be WHITE look darker than the black ones. Is the board flipped, "
                "or are you playing the other colour? Show the board from your side (use --color)."
            )
        self._recent = []
        self._base = self._examples(warped, expected)
        self._fit()
        wrong = self._predict(probe_occ, probe_col) != labels
        bad = tuple((int(i) // 8, int(i) % 8) for i in np.flatnonzero(wrong))
        return LearnReport(errors=len(bad), occupied=occupied, empty=64 - occupied, bad_cells=bad)

    def add_example(self, warped: np.ndarray, expected: np.ndarray) -> None:
        """Add a position that is known to be right (a confirmed game position) and retrain."""
        if self._model is None:
            return
        occ, col = cell_features(warped)
        self._recent.append((occ, col, expected.reshape(64).astype(int)))
        del self._recent[:-MAX_MEMORY]
        self._fit(incremental=True)

    def _fit(self, incremental: bool = False) -> None:
        memory = self._base + self._recent
        occ = np.vstack([m[0] for m in memory])
        col = np.vstack([m[1] for m in memory])
        labels = np.concatenate([m[2] for m in memory])
        occupied = (labels != EMPTY).astype(float)
        mask = labels != EMPTY
        old = self._model if incremental else None
        steps = 200 if incremental else 1500
        occ_mean, occ_std, occ_weights = _train_logistic(
            occ, occupied, steps=steps, start=(old.occ_mean, old.occ_std, old.occ_weights) if old else None)
        col_mean, col_std, col_weights = _train_logistic(
            col[mask], (labels[mask] == WHITE).astype(float), steps=steps,
            start=(old.col_mean, old.col_std, old.col_weights) if old else None)
        self._model = _Model(occ_mean, occ_std, occ_weights, col_mean, col_std, col_weights)

    # ---- reading
    def _scores(self, occ: np.ndarray, col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        m = self._model
        return _logistic(occ, m.occ_mean, m.occ_std, m.occ_weights), _logistic(col, m.col_mean, m.col_std, m.col_weights)

    def _predict(self, occ: np.ndarray, col: np.ndarray) -> np.ndarray:
        occupied, white = self._scores(occ, col)
        return np.where(occupied < 0.5, EMPTY, np.where(white >= 0.5, WHITE, BLACK)).astype(np.int8)

    def read(self, warped: np.ndarray, empty_hint=None) -> np.ndarray:
        """Classify every square of a warped board image into an 8x8 grid of EMPTY/WHITE/BLACK."""
        if self._model is None:
            raise RuntimeError("Reader has not learned from a known position yet.")
        occ, col = cell_features(warped)
        return self._predict(occ, col).reshape(8, 8)

    def read_scores(self, warped: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Probabilities (occupied, white) per square: for voting across frames and confidence."""
        occ, col = cell_features(warped)
        occupied, white = self._scores(occ, col)
        return occupied.reshape(8, 8), white.reshape(8, 8)
