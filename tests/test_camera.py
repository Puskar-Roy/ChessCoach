import chess
import cv2
import numpy as np
import pytest

import camera_input
import main
from calibration import Calibration
from camera_input import CameraEvent, CameraSession
from cli_input import Command
from game_state import GameState
from move_inference import expected_grid
from synth import FRAME_CORNERS, render_frame


class FakeCapture:
    def __init__(self, frames):
        self._frames = iter(frames)

    def read(self):
        try:
            return True, next(self._frames)
        except StopIteration:
            return False, None

    def grab(self):
        return True

    def release(self):
        pass


@pytest.fixture(autouse=True)
def no_gui(monkeypatch):
    monkeypatch.setattr(cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cv2, "waitKey", lambda *a, **k: -1)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda *a, **k: None)


def still(board, count, start_seed, color=chess.WHITE):
    return [render_frame(board, color, seed=start_seed + i) for i in range(count)]


def make_session(frames, color=chess.WHITE):
    session = CameraSession(color)
    session.calibration = Calibration(FRAME_CORNERS)
    start = chess.Board()
    warped = session.calibration.warp(render_frame(start, color, seed=0))
    session.reader.learn(warped, expected_grid(start, color))
    session._capture = FakeCapture(frames)
    return session


def run_until_empty(session, board):
    events = []
    while True:
        try:
            event = session.step(board)
        except camera_input.CameraError:
            return events
        if event is not None:
            events.append(event)
            if event.kind == "moves":
                for move in event.moves:
                    board.push(move)


def test_move_seen_after_hand_leaves():
    start = chess.Board()
    after = start.copy()
    after.push_san("e4")
    hand = render_frame(chess.Board("8/8/8/8/8/8/8/8 w - - 0 1"), chess.WHITE, seed=999)
    frames = still(start, 14, 10) + [hand] * 3 + still(after, 14, 50)
    events = run_until_empty(make_session(frames), start)
    assert [e.kind for e in events] == ["moves"]
    assert [m.uci() for m in events[0].moves] == ["e2e4"]


def test_no_event_while_board_is_moving_or_unchanged():
    start = chess.Board()
    frames = still(start, 30, 10)
    session = make_session(frames)
    assert run_until_empty(session, start) == []
    assert session._still >= camera_input.STILL_FRAMES  # it did reach a stable picture


def test_unclear_when_move_was_missed():
    start = chess.Board()
    far = start.copy()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4"]:
        far.push_san(san)
    frames = still(start, 12, 10) + still(far, 14, 50)
    events = run_until_empty(make_session(frames), start)
    assert [e.kind for e in events] == ["unclear"]
    assert "type it" in events[0].message


def test_black_user_sees_moves():
    start = chess.Board()
    after = start.copy()
    after.push_san("d4")
    frames = still(start, 12, 10, chess.BLACK) + still(after, 14, 50, chess.BLACK)
    events = run_until_empty(make_session(frames, chess.BLACK), start)
    assert [m.uci() for m in events[0].moves] == ["d2d4"]


class FakeReader:
    def __init__(self, commands):
        self._commands = list(commands)

    def get(self, timeout=None):
        return self._commands.pop(0) if self._commands else None


class FakeSession:
    def __init__(self, events):
        self._events = list(events)

    def step(self, board):
        return self._events.pop(0) if self._events else None

    def notify(self, text):
        self.notified = text


def test_next_command_prefers_typing_then_camera():
    state = GameState()
    move = chess.Move.from_uci("e2e4")
    session = FakeSession([None, CameraEvent("moves", moves=[move])])
    typed = main.next_command(FakeReader([Command("hint")]), session, state)
    assert typed.kind == "hint"
    camera = main.next_command(FakeReader([]), session, state)
    assert camera.kind == "camera_moves" and camera.moves == (move,)


def test_next_command_camera_quit_and_unclear(capsys):
    state = GameState()
    session = FakeSession([CameraEvent("unclear", message="please type it"), CameraEvent("quit")])
    assert main.next_command(FakeReader([]), session, state).kind == "quit"
    assert "please type it" in capsys.readouterr().out


def test_play_moves_applies_legal_sequence_and_stops_on_illegal():
    state = GameState()
    e4, e5 = chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")
    assert main.play_moves(state, (e4, e5))
    assert state.board.fullmove_number == 2
    assert not main.play_moves(state, (chess.Move.from_uci("e2e4"),))


def test_window_keys_map_to_commands():
    state = GameState()
    session = FakeSession([CameraEvent("hint"), CameraEvent("new_game"), CameraEvent("toggle_mute")])
    reader = FakeReader([])
    assert [main.next_command(reader, session, state).kind for _ in range(3)] == ["hint", "new", "toggle_mute"]


def test_lost_feed_falls_back_to_typing(capsys):
    class Dying:
        def step(self, board):
            raise camera_input.CameraError("Lost the board feed.")

    command = main.next_command(FakeReader([]), Dying(), GameState())
    assert command.kind == "camera_lost"
    assert "typed moves" in capsys.readouterr().out


def test_unclear_message_is_shown_on_screen():
    session = FakeSession([CameraEvent("unclear", message="not sure"), CameraEvent("quit")])
    main.next_command(FakeReader([]), session, GameState())
    assert session.notified == "not sure"


def test_status_line_tells_whose_turn_it_is():
    state = GameState(chess.WHITE)
    assert main.status_line(state) == "YOUR MOVE"
    state.push_text("e4")
    assert main.status_line(state) == "Opponent's move  (last: e4)"


def test_board_reset_to_start_is_flagged_as_new_game():
    played = chess.Board()
    played.push_san("e4")
    played.push_san("e5")
    frames = still(played, 12, 10) + still(chess.Board(), 40, 50)
    events = run_until_empty(make_session(frames), played)
    assert [e.kind for e in events] == ["unclear"]
    assert "new game" in events[0].message


def test_unclear_picture_is_reported_once_not_repeatedly():
    start = chess.Board()
    far = start.copy()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4"]:
        far.push_san(san)
    events = run_until_empty(make_session(still(start, 12, 10) + still(far, 80, 50)), start)
    assert len(events) == 1


def test_suggestion_carries_the_move_to_draw(monkeypatch):
    pytest.importorskip("chess.engine")
    from coach import Advice

    advice = Advice(parts=["Consider e4."], best_move=chess.Move.from_uci("e2e4"))
    assert advice.best_move.uci() == "e2e4"
