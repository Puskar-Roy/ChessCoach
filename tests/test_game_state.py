import chess
import pytest

from cli_input import parse_line
from game_state import GameState


def test_plays_san_and_tracks_turn():
    state = GameState(chess.WHITE)
    assert state.is_user_turn
    assert state.push_text("e4") == "e4"
    assert not state.is_user_turn
    state.push_text("e5")
    assert state.history_text() == "1. e4 e5"


@pytest.mark.parametrize("text", ["nf3", "Nf3", "g1f3", "  Nf3 "])
def test_lenient_parsing(text):
    assert GameState().parse_move(text) == chess.Move.from_uci("g1f3")


def test_lowercase_bishop_vs_pawn():
    state = GameState()
    for move in ["e4", "e5", "Bc4", "Nc6"]:
        state.push_text(move)
    assert state.parse_move("bb5") == chess.Move.from_uci("c4b5")
    assert state.parse_move("b3") == chess.Move.from_uci("b2b3")


def test_castling_zero_notation():
    state = GameState()
    for move in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]:
        state.push_text(move)
    assert state.push_text("0-0") == "O-O"


def test_illegal_move_message():
    with pytest.raises(ValueError, match="not a legal move"):
        GameState().parse_move("e5")


def test_ambiguous_move_message():
    state = GameState()
    for move in ["Nf3", "Nf6", "Nc3", "Nc6", "Ne4", "Ne5"]:
        state.push_text(move)
    with pytest.raises(ValueError, match="ambiguous"):
        state.parse_move("Ng5")


def test_undo():
    state = GameState()
    state.push_text("e4")
    assert state.undo() == "e2e4"
    assert state.undo() is None
    assert state.board.fen() == chess.STARTING_FEN


def test_game_over_result():
    state = GameState(chess.WHITE)
    for move in ["f3", "e5", "g4", "Qh4#"]:
        state.push_text(move)
    assert state.is_over
    assert "You lose" in state.result_text()
    with pytest.raises(ValueError, match="over"):
        state.parse_move("e4")


def test_render_flips_for_black():
    assert GameState(chess.BLACK).render().splitlines()[0].startswith("1")
    assert GameState(chess.WHITE).render().splitlines()[0].startswith("8")


def test_command_parsing():
    assert parse_line("UNDO").kind == "undo"
    assert parse_line("hint").kind == "hint"
    assert parse_line("Nf3").kind == "move"
    assert parse_line("  e4 ").text == "e4"


def test_custom_start_position_and_reset():
    fen = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"
    state = GameState(chess.WHITE, fen)
    state.push_text("Ra8#")
    assert state.history_text() == "1. Ra8#"
    state.reset()
    assert state.board.fen() == fen
    assert state.history_text() == "(no moves yet)"


def test_new_command_is_recognised():
    assert parse_line("new").kind == "new"
    assert parse_line("newgame").kind == "new"
