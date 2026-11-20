import chess
import numpy as np
import pytest

import sitegen
from move_inference import expected_grid
from piece_classifier import MODEL_PATH
from screen_reader import ScreenReader
from watcher import BoardWatcher, check_start_position, to_board_image


class FakeScreen:
    """A fake monitor showing a web page; the watcher reads the board region of it."""

    monitor_left = 0
    monitor_top = 0

    def __init__(self, page, rect):
        self.page = page
        x, y, size = rect
        self._region = {"left": x, "top": y, "width": size, "height": size}

    def read(self):
        r = self._region
        return True, self.page[r["top"] : r["top"] + r["height"], r["left"] : r["left"] + r["width"]].copy()

    def read_monitor(self):
        return self.page.copy()

    def set_region(self, x, y, width, height):
        self._region = {"left": x, "top": y, "width": width, "height": height}

    @property
    def region(self):
        return dict(self._region)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.05
        return self.now


def make_page(board, user_color, rng, cell=64, theme="green", style="classic", last=None, offset=None, background=None):
    image = sitegen.render_board(board, user_color, cell, theme, style, last_move=last, rng=np.random.default_rng(1))
    page, rect = sitegen.page_around(image, rng if background is None else background, margin_dark=True)
    return page, rect


def settle(watcher, board, steps=40):
    events = []
    for _ in range(steps):
        event = watcher.step(board)
        if event is not None:
            events.append(event)
    return events


@pytest.mark.parametrize("user_color", [chess.WHITE, chess.BLACK])
def test_start_position_and_side_are_recognised(user_color):
    image = sitegen.render_board(chess.Board(), user_color, 60, "brown", "classic")
    result = check_start_position(to_board_image(image))
    assert result.ok and result.user_color == user_color


def test_a_game_in_progress_is_not_taken_for_a_start_position():
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5"):
        board.push_san(san)
    result = check_start_position(to_board_image(sitegen.render_board(board, chess.WHITE, 60, "green", "classic")))
    assert not result.ok and "already under way" in result.message


def test_live_watching_follows_both_players():
    rng = np.random.default_rng(11)
    user = chess.WHITE
    board = chess.Board()
    page, rect = make_page(board, user, rng)
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    assert watcher.prepare(board).errors <= 1
    played = []
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Bxc6", "dxc6", "O-O", "Bg4"):
        move = board.parse_san(san)
        board.push(move)
        image = sitegen.render_board(board, user, rect[2] // 8, "green", "classic", last_move=move, rng=np.random.default_rng(1))
        screen.page[rect[1] : rect[1] + rect[2], rect[0] : rect[0] + rect[2]] = image
        events = [e for e in settle(watcher, chess.Board() if not played else replay(played)) if e.kind == "moves"]
        assert len(events) == 1 and events[0].moves == [move], san
        played.append(move)


def replay(moves):
    board = chess.Board()
    for move in moves:
        board.push(move)
    return board


def test_board_moved_on_the_page_is_found_again():
    rng = np.random.default_rng(4)
    user = chess.WHITE
    board = chess.Board()
    page, rect = make_page(board, user, rng)
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    watcher.prepare(board)
    settle(watcher, board, 20)
    # the page scrolls: the same picture, 130 px to the left and 70 px down
    shifted = np.roll(np.roll(page, 130, axis=1), 70, axis=0)
    screen.page = shifted
    events = settle(watcher, board, 120)
    relocked = [e for e in events if e.kind == "relocked"]
    assert relocked, [e.kind for e in events]
    region = screen.region
    assert abs(region["left"] - (rect[0] + 130)) <= 3 and abs(region["top"] - (rect[1] + 70)) <= 3


def test_covered_board_is_reported_then_recovered():
    rng = np.random.default_rng(9)
    user = chess.BLACK
    board = chess.Board()
    page, rect = make_page(board, user, rng)
    original = page.copy()
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    watcher.prepare(board)
    settle(watcher, board, 20)
    x, y, size = rect
    screen.page = page.copy()
    screen.page[y : y + size, x : x + size] = (40, 40, 40)  # a window covers the board
    kinds = [e.kind for e in settle(watcher, board, 100)]
    assert "lost" in kinds
    screen.page = original
    kinds = [e.kind for e in settle(watcher, board, 100)]
    assert "relocked" in kinds


@pytest.mark.parametrize("jump", [4, 6])
def test_moves_played_while_not_looking_are_caught_up(jump):
    """The opponent answers instantly and the player is quick: several moves appear between two looks."""
    rng = np.random.default_rng(5)
    user = chess.WHITE
    line = "d4 Nf6 Nf3 d6 Bf4 g5 Bxg5 Bd7 e3 Bg7 Bf4 Bb5 Bxb5+ c6 Bd3 O-O Nbd2 Nbd7 c3 e5".split()
    board = chess.Board()
    for san in line[:12]:
        board.push_san(san)
    page, rect = make_page(board, user, rng)
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    watcher.prepare(board)
    tracked = board.copy()
    expected = []
    for san in line[12 : 12 + jump]:
        move = board.parse_san(san)
        expected.append(move)
        board.push(move)
    image = sitegen.render_board(board, user, rect[2] // 8, "green", "classic", last_move=board.peek(), rng=np.random.default_rng(1))
    screen.page[rect[1] : rect[1] + rect[2], rect[0] : rect[0] + rect[2]] = image
    events = [e for e in settle(watcher, tracked, steps=200) if e.kind == "moves"]
    assert events, "the missing moves were not found"
    reached = tracked.copy()
    for move in events[0].moves:
        reached.push(move)
    # independent moves cannot be put in order from a single picture, so compare where the game ends up
    assert len(events[0].moves) == len(expected) and reached.board_fen() == board.board_fen() and reached.turn == board.turn


def _watch_a_change(plies_line, show_after, user=chess.WHITE, steps=300):
    """Track the board after `plies_line` plies, then show the position after `show_after` plies instead."""
    rng = np.random.default_rng(9)
    line = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O".split()
    tracked = chess.Board()
    for san in line[:plies_line]:
        tracked.push_san(san)
    shown = chess.Board()
    for san in line[:show_after]:
        shown.push_san(san)
    page, rect = make_page(tracked, user, rng)
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    watcher.prepare(tracked)
    image = sitegen.render_board(shown, user, rect[2] // 8, "green", "classic", last_move=shown.peek() if shown.move_stack else None, rng=np.random.default_rng(1))
    screen.page[rect[1] : rect[1] + rect[2], rect[0] : rect[0] + rect[2]] = image
    return settle(watcher, tracked, steps=steps), shown


def test_a_takeback_is_noticed():
    events, shown = _watch_a_change(12, 10)
    taken = [e for e in events if e.kind == "takeback"]
    assert taken and taken[0].plies == 2


def test_a_new_game_on_the_screen_counts_as_taking_everything_back():
    events, _ = _watch_a_change(12, 0, steps=300)
    taken = [e for e in events if e.kind == "takeback"]
    assert taken and taken[0].plies == 12


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="optional piece-recognition model is not installed")
def test_an_unrelated_position_is_adopted_as_it_is():
    rng = np.random.default_rng(9)
    user = chess.WHITE
    tracked = chess.Board()
    for san in "e4 e5 Nf3 Nc6 Bb5 a6".split():
        tracked.push_san(san)
    shown = chess.Board()
    for san in "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O".split():
        shown.push_san(san)
    page, rect = make_page(tracked, user, rng)
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    watcher.prepare(tracked)
    image = sitegen.render_board(shown, user, rect[2] // 8, "green", "classic", last_move=shown.peek(), rng=np.random.default_rng(1))
    screen.page[rect[1] : rect[1] + rect[2], rect[0] : rect[0] + rect[2]] = image
    adopted = [e for e in settle(watcher, tracked, steps=1200) if e.kind == "resync"]
    assert adopted and chess.Board(adopted[0].fen).board_fen() == shown.board_fen()


def test_a_piece_being_dragged_is_not_a_position():
    """Holding a piece over another square and thinking looks like a still picture; nothing may be read from it."""
    rng = np.random.default_rng(21)
    user = chess.BLACK
    tracked = chess.Board()
    for san in "e4 e5 Nf3 Nc6 Bb5".split():
        tracked.push_san(san)
    page, rect = make_page(tracked, user, rng)
    screen = FakeScreen(page, rect)
    held = {"down": False}
    watcher = BoardWatcher(screen, user, ScreenReader(), clock=Clock(), sleep=lambda s: None, mouse_down=lambda: held["down"])
    watcher.prepare(tracked)

    def show(board, move=None):
        image = sitegen.render_board(board, user, rect[2] // 8, "green", "classic", last_move=move, rng=np.random.default_rng(1))
        screen.page[rect[1] : rect[1] + rect[2], rect[0] : rect[0] + rect[2]] = image

    # the user lifts the d7 pawn and hovers over the white pawn on e4, deciding
    ghost = tracked.copy()
    ghost.remove_piece_at(chess.D7)
    ghost.set_piece_at(chess.E4, chess.Piece(chess.PAWN, chess.BLACK))
    held["down"] = True
    show(ghost)
    assert settle(watcher, tracked, steps=600) == [], "nothing may be reported or adopted while the button is held"
    # then drops it on d6
    held["down"] = False
    final = tracked.copy()
    move = final.parse_san("d6")
    final.push(move)
    show(final, move)
    events = [e for e in settle(watcher, tracked, steps=200) if e.kind in ("moves", "resync", "takeback")]
    assert len(events) == 1 and events[0].kind == "moves" and events[0].moves == [move]


def test_a_half_made_move_is_not_a_position_this_game_can_have_reached():
    from catch_up import plausible_successor

    before = chess.Board("rnbqkb1r/pp2p2p/6p1/2Q5/4P3/8/PPPP2PP/RNB1K1NR w KQkq - 1 7")
    dragged = chess.Board("rnbqkb1r/pp2p2p/6p1/4Q3/4p3/8/PPPP1PPP/RNB1K1NR b KQkq - 1 1")  # an extra black pawn on e4
    later = chess.Board("rnbqkb1r/pp2p2p/6p1/4Q3/4P3/8/PPPP2PP/RNB1K1NR b KQkq - 2 7")
    assert not plausible_successor(before, dragged)
    assert plausible_successor(before, later)
    assert plausible_successor(before, chess.Board())
