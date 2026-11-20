"""Find a chess board on a screenshot with no help from the user.

A chessboard is a lattice of 7x7 inner corners where the colour flips both ways. For every candidate
square size we build a "corner response" map from integral images (cheap), then look for the position
where the response alternates in sign along both axes (+ - + - ...). That signature is hard to fake:
text, photos and UI chrome do not produce a 7x7 alternating lattice, while pieces only weaken it.

The winner is then snapped to the exact pixel grid, and checked: it must be square, tile into 64 cells
with two alternating colours, and clearly stand out from the second-best candidate."""

from dataclasses import dataclass

import cv2
import numpy as np

from screen_capture import find_board

WORK_HEIGHT = 400  # the search runs on a downscaled copy; the result is refined at full resolution
MIN_SQUARE = 18  # smallest square (full-resolution pixels) we accept
MAX_SQUARE = 150


@dataclass(frozen=True)
class BoardCandidate:
    x: int
    y: int
    size: int
    confidence: float  # 0..1, how sure we are this is a board

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.size, self.size


def _integral(gray: np.ndarray) -> np.ndarray:
    return cv2.integral(gray, sdepth=cv2.CV_32F)


def _corner_response(integral: np.ndarray, s: int) -> np.ndarray:
    """Checker response at every pixel: (TL + BR) - (TR + BL) over four s x s blocks, normalised by area."""
    h, w = integral.shape[0] - 1, integral.shape[1] - 1
    if h < 2 * s + 1 or w < 2 * s + 1:
        return np.zeros((0, 0))
    block = integral[s:, s:] - integral[:-s, s:] - integral[s:, :-s] + integral[:-s, :-s]  # (h-s+1, w-s+1)
    response = block[:-s, :-s] + block[s:, s:] - block[:-s, s:] - block[s:, :-s]
    return response / (s * s)


def _lattice_score(response: np.ndarray, s: int) -> np.ndarray:
    """Alternating 7x7 sum of the response, for every top-left inner corner. Sign-agnostic (abs at the end)."""
    height, width = response.shape
    span = 6 * s
    if height <= span or width <= span:
        return np.zeros((0, 0))
    rows, cols = height - span, width - span
    along_x = np.zeros((height, cols), np.float32)
    for i in range(7):
        along_x += (-1) ** i * response[:, i * s : i * s + cols]
    along_y = np.zeros((rows, cols), np.float32)
    for j in range(7):
        along_y += (-1) ** j * along_x[j * s : j * s + rows, :]
    return np.abs(along_y) / 49.0


def _cell_stats(gray_lab: np.ndarray, x: int, y: int, size: int) -> float:
    """0..1 evidence that the 8x8 cells in this square alternate between two colours."""
    height, width = gray_lab.shape[:2]
    if x < 0 or y < 0 or x + size > width or y + size > height or size < 8 * 4:
        return 0.0
    cell = size / 8
    pad = max(1, int(cell * 0.2))
    medians = np.zeros((8, 8, 3))
    for r in range(8):
        for c in range(8):
            y0, y1 = int(y + r * cell) + pad, int(y + (r + 1) * cell) - pad
            x0, x1 = int(x + c * cell) + pad, int(x + (c + 1) * cell) - pad
            patch = gray_lab[y0:y1, x0:x1].reshape(-1, 3)
            medians[r, c] = np.median(patch, axis=0)
    parity = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)
    light, dark = medians[~parity], medians[parity]
    centre_a, centre_b = np.median(light, axis=0), np.median(dark, axis=0)
    separation = float(np.linalg.norm(centre_a - centre_b))
    near_a = np.linalg.norm(light - centre_a, axis=1) < 16
    near_b = np.linalg.norm(dark - centre_b, axis=1) < 16
    agreement = (near_a.sum() + near_b.sum()) / 64.0  # empty squares match their colour, pieces do not
    return float(min(1.0, agreement / 0.55) * min(1.0, separation / 12.0))


def _outward_penalty(lightness: np.ndarray, x: int, y: int, size: int) -> float:
    """How far the checker pattern keeps going just OUTSIDE this board (0 = stops at the edge, 1 = continues).

    A candidate that is shifted by one square lies partly inside the real board, so the alternating corner
    response carries on past its edge; the true board is surrounded by page, where it does not."""
    s_work = 24
    cell = size / 8
    f = s_work / cell
    pad = 2 * cell
    x0, y0 = int(round(x - pad)), int(round(y - pad))
    span = int(round((8 * cell + 2 * pad)))
    height, width = lightness.shape
    crop = np.full((span, span), float(np.median(lightness)), np.float32)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(width, x0 + span), min(height, y0 + span)
    if sx1 <= sx0 or sy1 <= sy0:
        return 0.0
    crop[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = lightness[sy0:sy1, sx0:sx1]
    side = 12 * s_work
    resized = cv2.resize(crop, (side, side), interpolation=cv2.INTER_AREA)
    response = _corner_response(_integral(resized), s_work)
    if response.size == 0:
        return 0.0

    def at(j, i):
        return response[(1 + j) * s_work, (1 + i) * s_work]

    inner = np.mean([abs(at(j, i)) for j in range(1, 8) for i in range(1, 8)]) + 1e-6
    signs = np.array([(-1.0) ** k for k in range(1, 8)])
    coherence = [
        abs(sum(sign * at(line, k) for sign, k in zip(signs, range(1, 8)))) / (7 * inner) for line in (-1, 9)
    ] + [
        abs(sum(sign * at(k, line) for sign, k in zip(signs, range(1, 8)))) / (7 * inner) for line in (-1, 9)
    ]
    return float(min(1.0, max(coherence)))


def lattice_strength(board_image: np.ndarray) -> float:
    """How strongly a picture of exactly one board (any size) shows the 7x7 alternating corner lattice.

    Used to check that the board is still where we think it is: the value collapses when the page
    scrolls, the window moves, or something covers the board."""
    side = 480
    image = board_image if board_image.shape[0] == side and board_image.shape[1] == side else cv2.resize(
        board_image, (side, side), interpolation=cv2.INTER_AREA)
    lightness = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
    s = side // 8
    response = _corner_response(_integral(lightness), s)
    samples = response[::s, ::s][:7, :7]
    signs = np.fromfunction(lambda j, i: (-1.0) ** (i + j), (7, 7))
    return float(abs((samples * signs).sum()) / 49.0)


def detect_boards(screen: np.ndarray, limit: int = 3) -> list[BoardCandidate]:
    """Boards found on a BGR screenshot, best first."""
    height = screen.shape[0]
    scale = min(1.0, WORK_HEIGHT / height)
    small = cv2.resize(screen, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else screen
    lab_small = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    full_lab = cv2.cvtColor(screen, cv2.COLOR_BGR2LAB).astype(np.float32)
    # Lightness is enough for nearly every board; colour-only boards (equal brightness) need the colour axes.
    for planes in ([lab_small[:, :, 0]], [lab_small[:, :, 0], lab_small[:, :, 1], lab_small[:, :, 2]]):
        found = _search(screen, full_lab, planes, scale, limit)
        if found and found[0].confidence >= 0.6:
            return found
    return found


def _search(screen: np.ndarray, full_lab: np.ndarray, planes: list, scale: float, limit: int) -> list[BoardCandidate]:
    integrals = [_integral(p) for p in planes]

    peaks: list[tuple[float, int, int, int]] = []  # (score, x_inner, y_inner, s) in work pixels
    lo = max(4, int(MIN_SQUARE * scale))
    hi = max(lo + 1, int(MAX_SQUARE * scale))
    for s in range(lo, hi + 1):
        total = None
        for integral, weight in zip(integrals, (1.0, 0.6, 0.6)[: len(integrals)]):
            response = _corner_response(integral, s)
            if response.size == 0:
                total = None
                break
            score = _lattice_score(response, s) * weight
            total = score if total is None else total + score
        if total is None or total.size == 0:
            continue
        # keep the best few distinct peaks at this size
        flat = total.ravel()
        for index in np.argpartition(flat, -3)[-3:]:
            peaks.append((float(flat[index]) / 1.0, int(index % total.shape[1]), int(index // total.shape[1]), s))
    if not peaks:
        return []

    peaks.sort(reverse=True)
    best_raw = peaks[0][0]
    lightness = full_lab[:, :, 0]
    scored: dict[tuple[int, int, int], float] = {}

    def consider(bx: int, by: int, bsize: int, strength: float) -> None:
        key = (bx, by, bsize)
        if key in scored or not MIN_SQUARE * 8 <= bsize <= MAX_SQUARE * 8:
            return
        evidence = _cell_stats(full_lab, bx, by, bsize)
        if evidence < 0.35:
            scored[key] = 0.0
            return
        penalty = _outward_penalty(lightness, bx, by, bsize)
        scored[key] = round(float(evidence * (0.5 + 0.5 * strength) * (1.0 - 0.85 * penalty)), 3)

    seeds = []
    for raw, x_inner, y_inner, s in peaks[:24]:
        if raw < 0.15 * best_raw:
            break
        size = 8 * s / scale
        rough = (int(round(x_inner / scale)), int(round(y_inner / scale)), int(round(size)), int(round(size)))
        snapped = find_board(screen, rough) or (rough[0], rough[1], rough[2])
        seeds.append((snapped, min(1.0, raw / max(best_raw, 1e-6))))
    for (bx, by, bsize), strength in seeds:
        consider(bx, by, bsize, strength)
    # A board shifted by one square looks almost as good as the real one, so try the neighbours too and let
    # the "pattern stops at the edge" test pick the right one.
    for (bx, by, bsize), strength in sorted(seeds, key=lambda item: -scored.get(item[0], 0))[:6]:
        cell = bsize // 8
        for dx, dy in ((0, -cell), (0, cell), (-cell, 0), (cell, 0)):
            consider(bx + dx, by + dy, bsize, strength * 0.9)

    results: list[BoardCandidate] = []
    for (bx, by, bsize), confidence in sorted(scored.items(), key=lambda item: -item[1]):
        if confidence <= 0:
            continue
        if any(abs(c.x - bx) < bsize * 0.2 and abs(c.y - by) < bsize * 0.2 and abs(c.size - bsize) < bsize * 0.2 for c in results):
            continue
        results.append(BoardCandidate(bx, by, bsize, confidence))
        if len(results) >= limit:
            break
    return results


def detect_board(screen: np.ndarray) -> BoardCandidate | None:
    found = detect_boards(screen, limit=2)
    if not found:
        return None
    best = found[0]
    # if a second board looks just as likely, we cannot tell which one the user means: lower the confidence
    if len(found) > 1 and found[1].confidence > 0.85 * best.confidence:
        best = BoardCandidate(best.x, best.y, best.size, round(best.confidence * 0.7, 3))
    return best
