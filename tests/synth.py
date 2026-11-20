"""Render fake camera frames of a chess position for testing the vision pipeline."""

import chess
import cv2
import numpy as np

from calibration import WARP_SIZE, SQUARE_SIZE
from move_inference import square_to_cell

LIGHT = (170, 210, 235)  # BGR
DARK = (70, 105, 150)
WHITE_PIECE = (225, 230, 235)
BLACK_PIECE = (40, 40, 45)

FRAME_W, FRAME_H = 640, 480
# where the board's TL, TR, BR, BL corners land in the camera frame (mild perspective)
FRAME_CORNERS = np.float32([[110, 60], [530, 70], [595, 425], [55, 415]])


HIGHLIGHT = (105, 246, 246)  # BGR, like a website's last-move colour


def render_topdown(
    board: chess.Board, user_color: bool, highlights=(), dots=(), highlight_alpha: float = 0.5
) -> np.ndarray:
    """Flat board image. `highlights` squares get a coloured background and `dots` squares a
    translucent move-hint dot, both drawn UNDER the pieces like a chess website does."""
    image = np.zeros((WARP_SIZE, WARP_SIZE, 3), dtype=np.uint8)
    marked = {square_to_cell(sq, user_color) for sq in highlights}
    dotted = {square_to_cell(sq, user_color) for sq in dots}
    for row in range(8):
        for col in range(8):
            color = LIGHT if (row + col) % 2 == 0 else DARK
            if (row, col) in marked:
                color = tuple(int((1 - highlight_alpha) * c + highlight_alpha * h) for c, h in zip(color, HIGHLIGHT))
            cv2.rectangle(
                image,
                (col * SQUARE_SIZE, row * SQUARE_SIZE),
                ((col + 1) * SQUARE_SIZE, (row + 1) * SQUARE_SIZE),
                color,
                -1,
            )
    for row, col in dotted:
        overlay = image.copy()
        center = (col * SQUARE_SIZE + SQUARE_SIZE // 2, row * SQUARE_SIZE + SQUARE_SIZE // 2)
        cv2.circle(overlay, center, SQUARE_SIZE // 6, (0, 0, 0), -1)
        image = cv2.addWeighted(overlay, 0.18, image, 0.82, 0)
    for square, piece in board.piece_map().items():
        row, col = square_to_cell(square, user_color)
        cx = col * SQUARE_SIZE + SQUARE_SIZE // 2
        cy = row * SQUARE_SIZE + SQUARE_SIZE // 2
        fill = WHITE_PIECE if piece.color == chess.WHITE else BLACK_PIECE
        edge = (30, 30, 30) if piece.color == chess.WHITE else (200, 200, 200)
        radius = int(SQUARE_SIZE * (0.2 + 0.03 * piece.piece_type))
        cv2.circle(image, (cx, cy), radius, fill, -1)
        cv2.circle(image, (cx, cy), radius, edge, 1)
        cv2.circle(image, (cx, cy - 6), radius // 2, fill, -1)
    return image


def render_frame(board: chess.Board, user_color: bool, seed: int = 0, noise: float = 4.0) -> np.ndarray:
    topdown = render_topdown(board, user_color)
    source = np.float32([[0, 0], [WARP_SIZE, 0], [WARP_SIZE, WARP_SIZE], [0, WARP_SIZE]])
    matrix = cv2.getPerspectiveTransform(source, FRAME_CORNERS)
    frame = cv2.warpPerspective(
        topdown, matrix, (FRAME_W, FRAME_H), borderValue=(90, 90, 90)
    ).astype(np.float32)

    rng = np.random.default_rng(seed)
    gradient = np.linspace(0.85, 1.1, FRAME_W, dtype=np.float32)[None, :, None]
    frame = frame * gradient + rng.normal(0, noise, frame.shape)
    return np.clip(frame, 0, 255).astype(np.uint8)
