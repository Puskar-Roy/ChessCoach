"""Simulate chess websites for testing the vision code: themes, piece sets, highlights, move hints,
user arrows, check glow, coordinates, screen-share compression, and a busy page around the board.

Everything here is deterministic given an `rng` (a numpy Generator)."""

import chess
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


GLYPH = {"p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚"}
FONT_CANDIDATES = [
    "C:/Windows/Fonts/seguisym.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
]


def _font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# (light, dark) square colours, RGB
THEMES = {
    "green": ((238, 238, 210), (118, 150, 86)),
    "brown": ((240, 217, 181), (181, 136, 99)),
    "blue": ((222, 227, 230), (140, 162, 173)),
    "purple": ((233, 225, 247), (138, 107, 209)),
    "gray": ((205, 205, 205), (125, 125, 125)),
    "midnight": ((178, 184, 200), (78, 88, 112)),
    "walnut": ((226, 200, 160), (150, 105, 70)),
    "contrast": ((250, 250, 250), (70, 70, 70)),
}
# (white fill, white outline, black fill, black outline), RGB
PIECE_STYLES = {
    "classic": ((250, 250, 246), (28, 30, 48), (30, 33, 50), (232, 235, 250)),
    "flat": ((255, 255, 255), (255, 255, 255), (25, 25, 25), (25, 25, 25)),
    "neo": ((248, 248, 248), (120, 120, 120), (52, 52, 52), (52, 52, 52)),
    "wood": ((246, 236, 208), (120, 90, 50), (92, 62, 40), (40, 25, 15)),
}
HIGHLIGHTS = {"yellow": (255, 255, 51), "lime": (155, 199, 0), "blue": (20, 85, 190)}


def _sprite(symbol: str, px: int, style: str) -> np.ndarray:
    white_fill, white_edge, black_fill, black_edge = PIECE_STYLES[style]
    is_white = symbol.isupper()
    fill, edge = (white_fill, white_edge) if is_white else (black_fill, black_edge)
    scale = 3
    size = px * scale
    font = _font(int(size * 0.88))
    stroke = max(1, size // 30)
    glyph = GLYPH[symbol.lower()]
    probe = ImageDraw.Draw(Image.new("RGBA", (size, size)))
    left, top, right, bottom = probe.textbbox((0, 0), glyph, font=font, stroke_width=stroke)
    x, y = (size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((x, y), glyph, font=font, fill=fill + (255,), stroke_width=stroke, stroke_fill=edge + (255,))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((x, y + size * 0.025), glyph, font=font, fill=(0, 0, 0, 90), stroke_width=stroke, stroke_fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.02))
    out = Image.alpha_composite(shadow, layer).resize((px, px), Image.LANCZOS)
    return np.asarray(out, dtype=np.float32)


def _blend(canvas: np.ndarray, box: tuple[int, int, int, int], color_rgb, alpha: float) -> None:
    x0, y0, x1, y1 = box
    region = canvas[y0:y1, x0:x1]
    region[:] = region * (1 - alpha) + np.array(color_rgb[::-1], dtype=np.float32) * alpha  # canvas is BGR


def _cell_box(square: int, user_color: bool, cell: int) -> tuple[int, int, int, int]:
    file, rank = chess.square_file(square), chess.square_rank(square)
    col, row = (file, 7 - rank) if user_color == chess.WHITE else (7 - file, rank)
    return col * cell, row * cell, (col + 1) * cell, (row + 1) * cell


def _center(square: int, user_color: bool, cell: int) -> tuple[int, int]:
    x0, y0, x1, y1 = _cell_box(square, user_color, cell)
    return (x0 + x1) // 2, (y0 + y1) // 2


def render_board(
    board: chess.Board,
    user_color: bool,
    cell: int = 90,
    theme: str = "green",
    style: str = "classic",
    last_move: chess.Move | None = None,
    highlight: str = "yellow",
    selected: int | None = None,
    dots: tuple[int, ...] = (),
    arrows: tuple[tuple[int, int], ...] = (),
    premove: tuple[int, ...] = (),
    check_glow: bool = True,
    coordinates: bool = True,
    texture: float | None = None,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """A top-down board as a website draws it. Returns BGR uint8 of (8*cell, 8*cell)."""
    rng = rng or np.random.default_rng(0)
    light, dark = THEMES[theme]
    size = cell * 8
    canvas = np.zeros((size, size, 3), np.float32)
    for row in range(8):
        for col in range(8):
            color = light if (row + col) % 2 == 0 else dark
            canvas[row * cell : (row + 1) * cell, col * cell : (col + 1) * cell] = color[::-1]
    if texture is None:
        texture = 6.0 if theme == "walnut" else 0.0
    if texture:
        grain = cv2.GaussianBlur(rng.normal(0, texture, (size, size)).astype(np.float32), (0, 0), 2.0)
        canvas += grain[:, :, None] * 2.2

    def mark(square, color, alpha):
        _blend(canvas, _cell_box(square, user_color, cell), color, alpha)

    if last_move is not None:
        mark(last_move.from_square, HIGHLIGHTS[highlight], 0.5)
        mark(last_move.to_square, HIGHLIGHTS[highlight], 0.5)
    if selected is not None:
        mark(selected, HIGHLIGHTS[highlight], 0.5)
    for square in premove:
        mark(square, (235, 97, 80), 0.55)
    if check_glow and board.is_check():
        king = board.king(board.turn)
        cx, cy = _center(king, user_color, cell)
        yy, xx = np.mgrid[0:size, 0:size]
        glow = np.clip(1 - np.hypot(xx - cx, yy - cy) / (cell * 0.75), 0, 1) ** 1.5 * 0.85
        canvas = canvas * (1 - glow[:, :, None]) + np.array((60, 60, 235), np.float32) * glow[:, :, None]

    if coordinates:  # small labels in the corner squares, like chess.com
        canvas = np.clip(canvas, 0, 255).astype(np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = max(0.3, cell / 130)
        for i in range(8):
            col = i
            row = i
            tone_file = dark if (7 + col) % 2 == 0 else light
            tone_rank = dark if (row + 0) % 2 == 0 else light
            letters = "abcdefgh" if user_color == chess.WHITE else "hgfedcba"
            cv2.putText(canvas, letters[col], (col * cell + cell - int(cell * 0.2), size - int(cell * 0.06)), font, scale,
                        tuple(int(v) for v in tone_file[::-1]), 1, cv2.LINE_AA)
            number = str(8 - row) if user_color == chess.WHITE else str(row + 1)
            cv2.putText(canvas, number, (int(cell * 0.04), row * cell + int(cell * 0.2)), font, scale, tuple(int(v) for v in tone_rank[::-1]), 1, cv2.LINE_AA)
        canvas = canvas.astype(np.float32)

    for square in dots:
        cx, cy = _center(square, user_color, cell)
        overlay = canvas.copy()
        if board.piece_at(square) is None:
            cv2.circle(overlay, (cx, cy), int(cell * 0.17), (0, 0, 0), -1, cv2.LINE_AA)
        else:
            cv2.circle(overlay, (cx, cy), int(cell * 0.47), (0, 0, 0), max(2, cell // 12), cv2.LINE_AA)
        canvas = canvas * 0.86 + overlay * 0.14

    sprites = {}
    for square, piece in board.piece_map().items():
        key = piece.symbol()
        if key not in sprites:
            sprites[key] = _sprite(key, cell, style)
        x0, y0, _, _ = _cell_box(square, user_color, cell)
        sprite = sprites[key]
        alpha = sprite[:, :, 3:4] / 255.0
        region = canvas[y0 : y0 + cell, x0 : x0 + cell]
        region[:] = region * (1 - alpha) + sprite[:, :, 2::-1] * alpha

    for start, end in arrows:  # a user-drawn arrow, drawn over everything
        overlay = canvas.copy()
        p1, p2 = _center(start, user_color, cell), _center(end, user_color, cell)
        cv2.arrowedLine(overlay, p1, p2, (80, 170, 40), max(4, cell // 6), cv2.LINE_AA, tipLength=0.35)
        canvas = canvas * 0.2 + overlay * 0.8
    return np.clip(canvas, 0, 255).astype(np.uint8)


def page_around(board_img: np.ndarray, rng: np.random.Generator, screen=(1920, 1080), margin_dark: bool | None = None):
    """Put the board on a busy page. Returns (screenshot BGR, (x, y, size))."""
    width, height = screen
    size = board_img.shape[0]
    dark_page = bool(rng.integers(0, 2)) if margin_dark is None else margin_dark
    base = (40, 38, 36) if dark_page else (238, 238, 240)
    page = np.full((height, width, 3), base, np.uint8)
    # gradient + panels + fake text lines + a photo-like noisy block
    page = (page + np.linspace(0, 14, width, dtype=np.float32)[None, :, None]).clip(0, 255).astype(np.uint8)
    ink = (210, 210, 215) if dark_page else (40, 40, 45)
    for _ in range(int(rng.integers(25, 60))):
        x, y = int(rng.integers(0, width - 120)), int(rng.integers(0, height - 20))
        cv2.putText(page, "".join(rng.choice(list("abcdefgh stuvwxyz ")) for _ in range(int(rng.integers(8, 40)))), (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, float(rng.uniform(0.4, 0.9)), ink, 1, cv2.LINE_AA)
    for _ in range(int(rng.integers(3, 8))):
        x0, y0 = int(rng.integers(0, width - 300)), int(rng.integers(0, height - 200))
        w, h = int(rng.integers(100, 500)), int(rng.integers(60, 300))
        tone = rng.integers(20, 235, 3).tolist()
        page[y0 : y0 + h, x0 : x0 + w] = tone
    photo = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
    page[40:240, width - 340 : width - 40] = cv2.GaussianBlur(photo, (0, 0), 6)
    x = int(rng.integers(20, max(21, width - size - 20)))
    y = int(rng.integers(20, max(21, height - size - 20)))
    shadow = page[y - 6 : y + size + 6, x - 6 : x + size + 6]
    shadow[:] = (shadow * 0.8).astype(np.uint8)
    page[y : y + size, x : x + size] = board_img
    return page, (x, y, size)


def screen_share(frame: np.ndarray, quality: int = 70, blur: float = 0.6, resize: float = 1.0) -> np.ndarray:
    """What a video call does to a shared screen: slight softness, scaling and JPEG blocks."""
    out = cv2.GaussianBlur(frame, (0, 0), blur) if blur else frame
    if resize != 1.0:
        out = cv2.resize(cv2.resize(out, None, fx=resize, fy=resize, interpolation=cv2.INTER_AREA), (frame.shape[1], frame.shape[0]),
                         interpolation=cv2.INTER_LINEAR)
    ok, encoded = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)
