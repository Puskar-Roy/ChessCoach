import chess

from openings import OpeningBook


def play(*sans):
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


def test_all_book_lines_are_legal_and_have_plans():
    book = OpeningBook.load()
    assert len(book.openings) > 50
    for opening in book.openings:
        board = chess.Board()
        for san in opening.moves:
            board.push_san(san)
        assert opening.plan_white and opening.plan_black, opening.name


def test_identifies_italian():
    match = OpeningBook.load().identify(play("e4", "e5", "Nf3", "Nc6", "Bc4"))
    assert match.opening.name == "Italian Game"
    assert match.current


def test_picks_most_specific():
    match = OpeningBook.load().identify(play("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"))
    assert match.opening.name == "Giuoco Piano"


def test_transposition():
    one = OpeningBook.load().identify(play("d4", "d5", "Nf3", "Nf6", "Bf4"))
    two = OpeningBook.load().identify(play("d4", "Nf6", "Nf3", "d5", "Bf4"))
    assert one.opening.name == two.opening.name == "London System"


def test_out_of_book_remembers_last_match():
    board = play("e4", "e5", "Nf3", "Nc6", "Bb5", "a6")
    match = OpeningBook.load().identify(board)
    assert match.opening.name == "Ruy Lopez"
    assert not match.current
    assert match.ply == 5


def test_starting_position_has_no_opening():
    assert OpeningBook.load().identify(chess.Board()) is None


def test_plan_for_color():
    opening = OpeningBook.load().identify(play("e4", "e5", "Nf3", "Nc6", "Bc4")).opening
    assert opening.plan_for(chess.WHITE) == opening.plan_white
    assert opening.plan_for(chess.BLACK) == opening.plan_black
