import zlib

import chess
import numpy as np
import pytest

import sitegen
from board_detect import detect_board, lattice_strength
from watcher import to_board_image

CASES = [(theme, style) for theme in ("green", "brown", "blue", "midnight", "walnut", "contrast") for style in ("classic", "neo")]


@pytest.mark.parametrize("theme,style", CASES)
def test_board_is_found_on_a_busy_page(theme, style):
    rng = np.random.default_rng(zlib.crc32(f"{theme}{style}".encode()) % 1000)
    board = chess.Board()
    for _ in range(int(rng.integers(0, 30))):
        if board.is_game_over():
            break
        board.push(rng.choice(list(board.legal_moves)))
    cell = int(rng.integers(36, 100))
    image = sitegen.render_board(board, chess.WHITE, cell, theme, style, last_move=board.peek() if board.move_stack else None, rng=rng)
    page, (x, y, size) = sitegen.page_around(image, rng)
    found = detect_board(page)
    assert found is not None, (theme, style)
    assert abs(found.x - x) <= 3 and abs(found.y - y) <= 3 and abs(found.size - size) <= 6, (found, (x, y, size))
    assert found.confidence >= 0.7


def test_board_is_found_through_screen_share_compression():
    rng = np.random.default_rng(3)
    image = sitegen.render_board(chess.Board(), chess.BLACK, 70, "green", "classic", rng=rng)
    page, (x, y, size) = sitegen.page_around(image, rng)
    squeezed = sitegen.screen_share(page, quality=55, blur=0.9, resize=0.8)
    found = detect_board(squeezed)
    assert found is not None and abs(found.x - x) <= 4 and abs(found.y - y) <= 4 and abs(found.size - size) <= 8


def test_a_page_without_a_board_finds_nothing():
    rng = np.random.default_rng(8)
    image = sitegen.render_board(chess.Board(), chess.WHITE, 60, "green", "classic", rng=rng)
    page, (x, y, size) = sitegen.page_around(image, rng)
    page[y - 10 : y + size + 10, x - 10 : x + size + 10] = (40, 40, 40)  # cover it
    found = detect_board(page)
    assert found is None or found.confidence < 0.6


def test_alignment_strength_drops_when_the_view_is_off():
    rng = np.random.default_rng(5)
    image = sitegen.render_board(chess.Board(), chess.WHITE, 60, "brown", "classic", rng=rng)
    aligned = lattice_strength(to_board_image(image))
    shifted = lattice_strength(to_board_image(np.roll(image, 30, axis=1)))  # half a square off
    assert shifted < 0.4 * aligned
