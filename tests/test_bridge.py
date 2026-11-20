import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine import EngineNotFound, find_stockfish
from piece_classifier import MODEL_PATH

ROOT = Path(__file__).resolve().parent.parent


class Client:
    def __init__(self, data_dir):
        env = {**os.environ, "CHESSCOACH_DATA": str(data_dir)}
        self.proc = subprocess.Popen([sys.executable, "-u", "bridge.py"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env)
        self.seen = []
        self.unread = []
        self._next = 1

    def call(self, cmd, args=None, timeout=30):
        request = self._next
        self._next += 1
        self.proc.stdin.write(json.dumps({"id": request, "cmd": cmd, "args": args or {}}) + "\n")
        self.proc.stdin.flush()
        return self.wait(lambda m: m.get("id") == request, timeout)

    def wait(self, predicate, timeout=30):
        for index, message in enumerate(self.unread):  # events can arrive before the reply we were waiting for
            if predicate(message):
                del self.unread[index]
                return message
        end = time.time() + timeout
        while time.time() < end:
            line = self.proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            self.seen.append(message)
            if predicate(message):
                return message
            self.unread.append(message)
        raise AssertionError(f"timed out; saw {[m.get('event') or m.get('id') for m in self.seen]}")

    def event(self, name, timeout=30):
        return self.wait(lambda m: m.get("event") == name, timeout)["data"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=15)


def test_protocol_round_trip_for_a_manual_game(tmp_path):
    try:
        find_stockfish()
    except EngineNotFound:
        pytest.skip("Stockfish not installed")
    client = Client(tmp_path)
    try:
        assert client.event("ready")["version"] == 1
        hello = client.call("hello")
        assert hello["ok"] and len(hello["data"]["systems"]) >= 7
        assert any(s["id"] == "english" and s["color"] == "white" for s in hello["data"]["systems"])
        started = client.call("session.start", {"source": "manual", "color": "white", "voice": False, "engine_time": 0.1,
                                                 "system": "english", "level": "Guided", "arrows": True})
        assert started["ok"]
        advice = client.event("advice")
        assert advice["best"] == "c2c4" and advice["plan"]
        client.call("session.command", {"kind": "move_text", "data": {"text": "c4"}})
        state = client.event("state")
        assert state["sans"] in ([], ["c4"])
        bad = client.call("nonsense")
        assert not bad["ok"]
        client.call("session.stop")
        client.event("stopped")
    finally:
        client.close()


def test_joining_a_game_in_progress_from_the_screen(tmp_path, monkeypatch):
    """Inspect the pieces of a mid-game board, correct the groups, build the FEN, learn it and follow the next move."""
    import io

    import chess
    import numpy as np

    import bridge
    import sitegen
    from move_inference import square_to_cell
    from test_watcher import Clock, FakeScreen
    from watcher import BoardWatcher

    monkeypatch.setenv("CHESSCOACH_DATA", str(tmp_path))
    rng = np.random.default_rng(31)
    user = chess.BLACK
    board = chess.Board()
    for san in "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6 f3 Nbd7 Qd2 b5".split():
        board.push_san(san)
    image = sitegen.render_board(board, user, 64, "brown", "classic", last_move=board.peek(), rng=np.random.default_rng(1))
    page, (x, y, size) = sitegen.page_around(image, rng, margin_dark=True)
    screen = FakeScreen(page, (x, y, size))

    app = bridge.Bridge(io.StringIO())
    app.capture = screen
    app.monitor_screen = page
    seen = app.handle("capture.inspect", {"x": x, "y": y, "size": size})
    assert seen["ok"] and seen["userColor"] in ("white", "black")

    truth = {}
    for square, piece in board.piece_map().items():
        row, col = square_to_cell(square, user)
        truth[row * 8 + col] = piece
    cells = {}
    for group in seen["groups"]:  # the user fixes each group; here we give the true kind of its first square
        kind = truth[group["squares"][0]].piece_type
        for square in group["squares"]:
            cells[square] = chess.piece_symbol(kind).upper() if group["color"] == "w" else chess.piece_symbol(kind)
    built = app.handle("fen.build", {"cells": cells, "userColor": "black", "turn": "w", "castling": "auto"})
    assert built["ok"], built
    assert built["fen"].split()[0] == board.board_fen()

    result = app.handle("capture.confirm", {"x": x, "y": y, "size": size, "fen": built["fen"], "color": "black"})
    assert result["ok"] and result["color"] == "black" and result["fen"]

    watcher = app.watcher
    watcher._clock, watcher._sleep = Clock(), lambda s: None
    live = chess.Board(result["fen"])
    move = live.parse_san("Bd3")
    after = live.copy()
    after.push(move)
    page[y : y + size, x : x + size] = sitegen.render_board(after, user, size // 8, "brown", "classic", last_move=move, rng=np.random.default_rng(1))
    events = []
    for _ in range(40):
        event = watcher.step(live)
        if event is not None:
            events.append(event)
    assert [e.kind for e in events] == ["moves"] and events[0].moves == [move]


@pytest.mark.skipif(os.environ.get("CHESSCOACH_TEST_DESKTOP") != "1", reason="requires an interactive desktop")
def test_screen_capture_can_be_created_on_one_thread_and_read_on_another():
    """The app takes the screenshot on the bridge thread and watches the board on the game thread."""
    from concurrent.futures import ThreadPoolExecutor

    from screen_capture import ScreenCapture

    capture = ScreenCapture(1)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(capture.read).result()[0]
            assert pool.submit(capture.read_monitor).result().ndim == 3
    finally:
        capture.release()
    assert capture.read() == (False, None)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="optional piece-recognition model is not installed")
def test_a_game_under_way_can_be_joined_with_no_questions_asked(tmp_path, monkeypatch):
    import io

    import chess
    import numpy as np

    import bridge
    import sitegen
    from test_watcher import FakeScreen

    monkeypatch.setenv("CHESSCOACH_DATA", str(tmp_path))
    rng = np.random.default_rng(8)
    user = chess.WHITE
    board = chess.Board()
    for san in "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 h6 Bh4 b6 cxd5 exd5".split():
        board.push_san(san)
    image = sitegen.render_board(board, user, 64, "blue", "wood", last_move=board.peek(), rng=np.random.default_rng(2))
    page, (x, y, size) = sitegen.page_around(image, rng, margin_dark=True)
    app = bridge.Bridge(io.StringIO())
    app.capture = FakeScreen(page, (x, y, size))
    app.monitor_screen = page

    refused = app.handle("capture.confirm", {"x": x, "y": y, "size": size})
    assert not refused["ok"] and refused["joinable"]
    seen = app.handle("capture.inspect", {"x": x, "y": y, "size": size})
    assert seen["ok"] and seen["confident"], seen.get("sure")
    position = seen["position"]
    assert chess.Board(position["fen"]).board_fen() == board.board_fen()
    assert position["userColor"] == "white" and position["turn"] == "w"
    started = app.handle("capture.confirm", {"x": x, "y": y, "size": size, "fen": position["fen"], "color": position["userColor"]})
    assert started["ok"] and started["fen"]
