import chess
import pytest
from chess.engine import Cp, PovScore

from coach import Coach, render, speak_san
from engine import Engine, EngineNotFound, Line
from openings import OpeningBook


@pytest.fixture(scope="module")
def engine():
    try:
        instance = Engine(time_limit=0.15)
    except EngineNotFound:
        pytest.skip("Stockfish not installed")
    yield instance
    instance.close()


def make_coach(engine, color=chess.WHITE):
    return Coach(engine, OpeningBook.load(), color)


def play(*sans):
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


def test_speak_san():
    assert speak_san("Nf3") == "Knight f3"
    assert speak_san("exd5") == "e takes d5"
    assert speak_san("Qxf7#") == "Queen takes f7 checkmate"
    assert speak_san("O-O") == "castle kingside"
    assert speak_san("O-O-O+") == "castle queenside check"
    assert speak_san("e8=Q") == "e8 promotes to queen"


def test_render_markers():
    assert render("Play <<Nf3>>.") == "Play Nf3."
    assert render("Play <<Nf3>>.", speech=True) == "Play Knight f3."


def test_engine_finds_mate_in_one(engine):
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
    lines = engine.analyse(board)
    assert lines[0].san == "Ra8#"
    assert lines[0].mate(chess.WHITE) == 1


def test_start_position_advice(engine):
    advice = make_coach(engine).advise(chess.Board())
    assert advice.text.startswith("Consider ")
    assert advice.detail


def test_opening_named_and_plan_given(engine):
    coach = make_coach(engine, chess.WHITE)
    board = play("e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6")
    text = coach.advise(board).text
    assert "Two Knights Defense" in text
    assert "Consider" in text


def test_blunder_feedback(engine):
    coach = make_coach(engine, chess.WHITE)
    board = play("e4", "e5", "Qh5", "Nc6", "Qxe5+")
    text = coach.advise(board).text
    assert "That was a mistake" in text or "blunder" in text


def test_opponent_blunder_noticed(engine):
    coach = make_coach(engine, chess.WHITE)
    board = play("e4", "f5", "exf5", "g5")
    text = coach.advise(board).text
    assert "blundered" in text
    assert "checkmate in 1" in text


def test_winning_move_explained(engine):
    coach = make_coach(engine, chess.WHITE)
    board = chess.Board("4k3/8/8/3n4/8/8/8/3QK3 w - - 0 1")
    line = Line(
        move=chess.Move.from_uci("d1d5"),
        san="Qxd5",
        score=PovScore(Cp(0), chess.WHITE),
        pv=(chess.Move.from_uci("d1d5"),),
        pv_san=("Qxd5",),
    )
    assert coach._explain(board, line) == "It wins a free knight on d5."


def test_fork_explained(engine):
    coach = make_coach(engine, chess.WHITE)
    board = chess.Board("r3k3/8/4N3/8/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("e6c7")
    line = Line(move, "Nc7+", PovScore(Cp(0), chess.WHITE), (move,), ("Nc7+",))
    text = coach._explain(board, line)
    assert "forks" in text and "gives check" in text


def test_checkmate_announced(engine):
    coach = make_coach(engine, chess.WHITE)
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
    assert "checkmate in 1" in coach.advise(board).text


def test_game_over_message(engine):
    coach = make_coach(engine, chess.WHITE)
    board = play("f3", "e5", "g4", "Qh4#")
    assert "lost" in coach.advise(board).text


def test_hint_when_not_users_turn(engine):
    coach = make_coach(engine, chess.BLACK)
    assert "opponent's turn" in coach.hint(chess.Board()).text


def test_both_new_moves_get_feedback_and_a_suggestion(engine):
    # The camera can see two moves at once: the user's reply and the opponent's answer.
    coach = make_coach(engine, chess.WHITE)
    board = play("e4", "e5")
    text = coach.advise(board, new_moves=2).text
    assert text.count("Consider ") == 1
    assert "Excellent" in text or "Good move" in text or "playable" in text
