import chess
import pytest

import repertoire
from coach import render
from engine import Engine, EngineNotFound
from openings import OpeningBook
from trainer import TrainerCoach


@pytest.mark.parametrize("system", list(repertoire.SYSTEMS.values()), ids=lambda s: s.id)
def test_every_line_is_legal_and_notes_point_at_real_moves(system):
    assert system.lines and system.setup and system.ideas and system.middlegame and system.endgame
    for line in system.lines:
        board = chess.Board()
        tokens = line.moves.split()
        for san in tokens:
            board.push_san(san)  # raises if a line contains an illegal move
        assert all(0 <= ply < len(tokens) for ply in line.notes), line.name


def test_book_follows_the_english():
    english = repertoire.ENGLISH
    board = chess.Board()
    assert english.book_move(board).san == "c4"
    board.push_san("c4")
    board.push_san("e5")
    assert english.book_move(board).san == "Nc3"
    assert english.in_book(board)
    board.push_san("Nc3")
    board.push_san("a6")  # not in any line
    assert english.in_book(board) is None


def test_setup_steps_keep_working_after_the_book_ends():
    english = repertoire.ENGLISH
    board = chess.Board()
    for san in ("c4", "h6", "Nc3", "a6"):
        board.push_san(san)
    first_step, moves = english.next_setup(board)[0]
    assert board.san(moves[0]) == "Nf3"  # Nc3 is done, the next step of the English setup is Nf3


def test_system_only_applies_to_the_right_first_move():
    board = chess.Board()
    board.push_san("d4")
    assert not repertoire.CARO_KANN.applies(board)
    assert repertoire.KINGS_INDIAN.applies(board)
    assert repertoire.ENGLISH.applies(board)


@pytest.fixture(scope="module")
def engine():
    try:
        instance = Engine(time_limit=0.12)
    except EngineNotFound:
        pytest.skip("Stockfish not installed")
    yield instance
    instance.close()


def coach_for(engine, system=repertoire.ENGLISH, color=chess.WHITE, level="Guided", tolerance=130):
    return TrainerCoach(engine, OpeningBook.load(), color, system, level, tolerance)


def play(*sans):
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


def test_guided_coach_follows_the_english_whatever_the_engine_prefers(engine):
    coach = coach_for(engine)
    advice = coach.advise(chess.Board())
    assert advice.best_move == chess.Move.from_uci("c2c4")
    assert "c4" in advice.text
    board = play("c4", "e5")
    advice = coach.advise(board)
    assert advice.best_move == chess.Move.from_uci("b1c3")
    assert "Sicilian" in advice.text  # explains what Black's ...e5 means


def test_practice_level_hides_the_move_until_hint(engine):
    coach = coach_for(engine, level="Practice")
    board = play("c4", "e5")
    advice = coach.advise(board)
    assert advice.best_move is None and advice.best_move_hidden is not None
    assert "Nc3" not in render(advice.text)
    assert coach.hint(board).best_move == chess.Move.from_uci("b1c3")


def test_user_move_is_judged_against_the_system(engine):
    coach = coach_for(engine)
    board = play("c4", "e5", "Nc3")
    text = coach.advise(board, new_moves=1).text
    assert "Nc3" in text and coach.system_stats() == {"followed": 1, "total": 1}
    early = play("c4", "e5", "a3")  # an English move, but the line wants Nc3 first
    assert "a little early" in coach_for(engine).advise(early, new_moves=1).text
    off = play("c4", "e5", "h3")  # not an English move at all
    assert "leaves the system" in coach_for(engine).advise(off, new_moves=1).text


def test_a_system_move_that_loses_material_is_overridden(engine, monkeypatch):
    from chess.engine import Cp, PovScore

    from engine import Line

    coach = coach_for(engine)
    board = play("c4", "e5")
    other = chess.Move.from_uci("d2d4")  # pretend the engine prefers something else
    fake = Line(other, "d4", PovScore(Cp(30), chess.WHITE), (other,), ("d4",))
    monkeypatch.setattr(coach, "analyse", lambda b: [fake])
    monkeypatch.setattr(coach, "_loss", lambda b, m, cp: (400, [], b))  # every candidate drops material
    advice = coach.advise(board)
    assert "loses material" in advice.text
    assert advice.best_move == other


def test_coach_explains_an_unknown_opponent_move_and_phases(engine):
    coach = coach_for(engine)
    board = play("c4", "h6")
    text = coach.advise(board, new_moves=1).text
    assert "outside the lines I know" in text
    assert repertoire.phase(chess.Board(), setup_done=False) == "opening"
    assert repertoire.phase(chess.Board("8/5pk1/8/8/8/8/5PK1/8 w - - 0 40"), setup_done=True) == "endgame"
    assert "king" in repertoire.endgame_tip(chess.Board("8/5pk1/8/8/8/8/5PK1/8 w - - 0 40"))


def test_wrong_first_move_switches_a_black_system_off(engine):
    coach = coach_for(engine, repertoire.CARO_KANN, chess.BLACK)
    text = coach.advise(play("d4"), new_moves=1).text
    assert "not a Caro-Kann" in text
    assert coach.active is False
