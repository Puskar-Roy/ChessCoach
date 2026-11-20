import chess

import tactics


def test_knight_fork_detected():
    board = chess.Board("r3k3/8/4N3/8/8/8/8/4K3 w - - 0 1")
    found = tactics.forks(board, chess.WHITE)
    assert any(m.move == chess.Move.from_uci("e6c7") for m in found)
    motif = next(m for m in found if m.move == chess.Move.from_uci("e6c7"))
    assert "king" in motif.text and "rook" in motif.text


def test_fork_threat_against_player():
    board = chess.Board("r3k3/8/4N3/8/8/8/8/4K3 b - - 0 1")
    threats = tactics.fork_threats(board, chess.BLACK)
    assert any(san == "Nc7+" for san, _ in threats)


def test_unsafe_fork_not_reported():
    # a black rook on c8 guards c7, so the knight would just be captured
    board = chess.Board("r1r1k3/8/4N3/8/8/8/8/4K3 w - - 0 1")
    found = tactics.forks(board, chess.WHITE)
    assert not any(m.move == chess.Move.from_uci("e6c7") for m in found)


def test_pin_detected():
    board = chess.Board("4k3/4n3/8/8/8/8/8/4R1K1 w - - 0 1")
    kinds = [(m.kind, m.text) for m in tactics.pins_and_skewers(board, chess.WHITE)]
    assert ("pin", "pins the knight on e7 to the king on e8") in kinds
    assert tactics.pinned_pieces(board, chess.BLACK) == [chess.E7]


def test_skewer_detected():
    board = chess.Board("4r3/8/8/8/4k3/8/8/4R1K1 b - - 0 1")
    kinds = [m.kind for m in tactics.pins_and_skewers(board, chess.WHITE)]
    assert "skewer" in kinds


def test_hanging_piece():
    board = chess.Board("4k3/8/8/3n4/8/8/8/3QK3 w - - 0 1")
    assert tactics.hanging_pieces(board, chess.BLACK) == [chess.D5]
    assert tactics.hanging_pieces(board, chess.WHITE) == []


def test_defended_piece_not_hanging_unless_outvalued():
    board = chess.Board("4k3/8/2p5/3n4/8/8/8/3QK3 w - - 0 1")
    assert tactics.hanging_pieces(board, chess.BLACK) == []
    board = chess.Board("4k3/8/2p5/3q4/8/8/8/3RK3 w - - 0 1")
    assert tactics.hanging_pieces(board, chess.BLACK) == [chess.D5]


def test_discovered_check():
    board = chess.Board("4k3/8/8/8/8/8/4B3/4R1K1 w - - 0 1")
    found = tactics.discovered_attacks(board, chess.WHITE)
    assert found
    assert all(m.move.from_square == chess.E2 for m in found)
    assert "check" in found[0].text


def test_motifs_for_move_reports_fork():
    board = chess.Board("r3k3/8/4N3/8/8/8/8/4K3 w - - 0 1")
    motifs = tactics.motifs_for_move(board, chess.Move.from_uci("e6c7"))
    assert any(m.kind == "fork" for m in motifs)
