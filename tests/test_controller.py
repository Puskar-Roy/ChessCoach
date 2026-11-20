import queue
import time

import chess
import pytest

import controller as ctl
import settings as store
from engine import EngineNotFound, find_stockfish


@pytest.fixture(autouse=True)
def need_engine():
    try:
        find_stockfish()
    except EngineNotFound:
        pytest.skip("Stockfish not installed")


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    original = store.add_history
    monkeypatch.setattr(ctl.store, "add_history", lambda entry: original(entry, tmp_path / "history.json"))


def drain(events, wait=0.0):
    out = []
    deadline = time.time() + wait
    while True:
        try:
            out.append(events.get(timeout=max(0.01, deadline - time.time())))
        except queue.Empty:
            return out


def wait_for(events, kind, timeout=15):
    seen = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            item = events.get(timeout=0.2)
        except queue.Empty:
            continue
        seen.append(item)
        if item[0] == kind:
            return item, seen
    raise AssertionError(f"no {kind!r} event, saw {[k for k, _ in seen]}")


def test_manual_session_gives_advice_and_state():
    events = queue.Queue()
    controller = ctl.GameController({"voice": False, "engine_time": 0.1, "arrows": True}, events)
    controller.start(chess.WHITE, "Manual")
    started, _ = wait_for(events, "started")
    assert started[1]["color"] == chess.WHITE
    advice, _ = wait_for(events, "advice")
    assert advice[1]["text"].startswith("Consider ")
    assert advice[1]["best"] and len(advice[1]["lines"]) >= 1

    controller.send("move_text", text="e4")
    reply, seen = wait_for(events, "advice")
    assert "Now wait for your opponent" in reply[1]["text"]
    assert reply[1]["best"] is None  # nothing to draw while the opponent thinks

    controller.send("move_uci", uci="e7e5")
    follow_up, _ = wait_for(events, "advice")
    assert follow_up[1]["best"] is not None

    controller.stop()
    assert not controller.running


def test_illegal_move_is_reported_not_played():
    events = queue.Queue()
    controller = ctl.GameController({"voice": False, "engine_time": 0.1, "arrows": True}, events)
    controller.start(chess.WHITE, "Manual")
    wait_for(events, "advice")
    controller.send("move_uci", uci="e2e5")
    notice, _ = wait_for(events, "notice")
    assert "not legal" in notice[1]
    controller.stop()


def test_accuracy_stats():
    stats = ctl.accuracy_stats({1: ("best", 0), 3: ("blunder", 400)})
    assert stats["moves"] == 2 and stats["counts"]["blunder"] == 1 and stats["accuracy"] == 50.0


def _live_setup(user_color):
    """A fake monitor showing a simulated chess site, and a watcher already taught the start position."""
    import numpy as np

    import sitegen
    from screen_reader import ScreenReader
    from test_watcher import Clock, FakeScreen
    from watcher import BoardWatcher

    rng = np.random.default_rng(21)
    image = sitegen.render_board(chess.Board(), user_color, 60, "green", "classic", rng=np.random.default_rng(1))
    page, rect = sitegen.page_around(image, rng, margin_dark=True)
    screen = FakeScreen(page, rect)
    watcher = BoardWatcher(screen, user_color, ScreenReader(), clock=Clock(), sleep=lambda s: None)
    watcher.prepare(chess.Board())

    def show(board, move=None):
        x, y, size = rect
        page[y : y + size, x : x + size] = sitegen.render_board(
            board, user_color, size // 8, "green", "classic", last_move=move, rng=np.random.default_rng(1))

    return watcher, show


@pytest.mark.parametrize("user_color", [chess.WHITE, chess.BLACK])
def test_screen_session_sees_my_move_and_the_opponents_reply(user_color):
    watcher, show = _live_setup(user_color)
    events = queue.Queue()
    controller = ctl.GameController({"voice": False, "engine_time": 0.1, "arrows": True, "monitor": 1}, events)
    controller.start(user_color, "Screen", watcher=watcher)
    started, _ = wait_for(events, "started")
    assert started[1]["source"] == "Screen" and started[1]["region"]
    board = chess.Board()

    sequence = ["e4", "e5", "Nf3", "Nc6"] if user_color == chess.WHITE else ["e4", "e5", "d4", "exd4"]
    for ply, san in enumerate(sequence):
        move = board.parse_san(san)
        board.push(move)
        show(board, move)
        state, _ = wait_for(events, "state", timeout=30)
        while len(state[1]["sans"]) < ply + 1:
            state, _ = wait_for(events, "state", timeout=30)
        assert state[1]["sans"][-1] == san, (ply, state[1]["sans"])
    controller.stop()


def test_instant_reply_is_read_as_two_moves():
    """A bot that answers instantly: my move and its reply appear on screen together."""
    watcher, show = _live_setup(chess.WHITE)
    events = queue.Queue()
    controller = ctl.GameController({"voice": False, "engine_time": 0.1, "arrows": True, "monitor": 1}, events)
    controller.start(chess.WHITE, "Screen", watcher=watcher)
    wait_for(events, "started")
    board = chess.Board()
    for san in ("e4", "c5"):
        move = board.parse_san(san)
        board.push(move)
    show(board, move)
    state, _ = wait_for(events, "state", timeout=30)
    while len(state[1]["sans"]) < 2:
        state, _ = wait_for(events, "state", timeout=30)
    assert state[1]["sans"] == ["e4", "c5"]
    controller.stop()


def test_training_session_follows_the_chosen_opening():
    events = queue.Queue()
    settings = {"voice": False, "engine_time": 0.1, "arrows": True, "system": "english", "level": "Guided",
                "strictness": "Balanced"}
    controller = ctl.GameController(settings, events)
    controller.start(chess.BLACK, "Manual")  # the English is a White system: the controller plays it from White
    started, _ = wait_for(events, "started")
    assert started[1]["color"] == chess.WHITE and started[1]["system"] == "English Opening"
    advice, _ = wait_for(events, "advice")
    assert advice[1]["best"] == "c2c4" and advice[1]["plan"] and advice[1]["phase"] == "opening"

    controller.send("move_text", text="c4")
    state, _ = wait_for(events, "state")
    reply, _ = wait_for(events, "advice")
    assert "English" in reply[1]["text"] or "c4" in reply[1]["text"]
    controller.send("move_uci", uci="e7e5")
    follow, _ = wait_for(events, "advice")
    assert follow[1]["best"] == "b1c3"
    latest = None
    for kind, data in drain(events, wait=1.0):
        if kind == "state":
            latest = data
    assert latest and latest["system"]["followed"] >= 1
    controller.send("level", level="Practice")
    controller.send("move_text", text="Nc3")
    practice, _ = wait_for(events, "advice")
    controller.send("move_uci", uci="g8f6")
    practice, _ = wait_for(events, "advice")
    assert practice[1]["best"] is None  # Practice: the arrow stays hidden until Hint
    controller.send("hint")
    hint, _ = wait_for(events, "advice")
    assert hint[1]["best"] is not None
    controller.stop()


def test_joining_a_game_in_progress_ignores_the_opening_system_and_can_flip_the_turn():
    fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R b KQkq - 1 5"
    events = queue.Queue()
    settings = {"voice": False, "engine_time": 0.1, "arrows": True, "system": "english", "level": "Guided", "strictness": "Balanced"}
    controller = ctl.GameController(settings, events)
    controller.start(chess.WHITE, "Manual", fen)
    started, seen = wait_for(events, "started")
    assert started[1]["joined"] is True and started[1]["system"] is None
    assert any(kind == "notice" and "joined a game" in data for kind, data in seen)
    state, _ = wait_for(events, "state")
    assert state[1]["fen"].split()[1] == "b" and state[1]["user_turn"] is False  # Black to move: waiting for the opponent
    controller.send("flip_turn")
    advice, _ = wait_for(events, "advice")
    assert "setup" not in advice[1]["text"].lower() and advice[1]["best"]  # real advice for White now, no opening plan
    controller.stop()


class ScriptedWatcher:
    """Stands in for the screen watcher: hands out prepared events, one per step."""

    def __init__(self, events):
        self.script = list(events)
        self.capture = type("Cap", (), {"region": {"left": 0, "top": 0, "width": 400, "height": 400}})()

    def step(self, board):
        return self.script.pop(0) if self.script else None

    def status(self):
        return "watching"

    def resync(self):
        pass

    def reread(self):
        pass

    def close(self):
        pass


def test_caught_up_moves_takebacks_and_new_positions_reach_the_game():
    from watcher import WatchEvent

    board = chess.Board()
    moves = []
    for san in ("e4", "e5", "Nf3", "Nc6"):
        moves.append(board.push_san(san))
    elsewhere = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
    script = [
        WatchEvent("moves", moves, message="I had missed 4 moves, so I caught up."),
        WatchEvent("takeback", plies=2, message="You took back 2 moves."),
        WatchEvent("resync", fen=elsewhere, message="re-read"),
    ]
    events = queue.Queue()
    settings = {"voice": False, "engine_time": 0.1, "arrows": True, "system": "", "level": "Guided", "strictness": "Balanced"}
    controller = ctl.GameController(settings, events)
    controller.start(chess.WHITE, "Screen", None, ScriptedWatcher(script))
    seen = []
    deadline = time.time() + 30
    fens = []
    while time.time() < deadline and not (fens and fens[-1][1].split()[0] == chess.Board(elsewhere).board_fen()):
        try:
            kind, data = events.get(timeout=1)
        except queue.Empty:
            continue
        seen.append(kind)
        if kind == "state":
            fens.append((len(data["sans"]), data["fen"]))
    controller.stop()
    counts = [n for n, _ in fens]
    assert 4 in counts and 2 in counts, counts  # four moves caught up, then two taken back
    assert fens[-1][1].split()[0] == chess.Board(elsewhere).board_fen()  # and the new position adopted
