"""Opening systems to learn: the ideas, the setup to aim for, and the main lines with explanations.

A *system* is a way of playing, not a single move list. The coach follows it whatever the engine says,
as long as the move is not a blunder, so you learn the plans instead of just copying the best move.

Notes in a line are keyed by ply (0 = White's first move, 1 = Black's first reply, ...)."""

from dataclasses import dataclass, field

import chess

WHITE, BLACK = chess.WHITE, chess.BLACK


@dataclass(frozen=True)
class SetupStep:
    moves: tuple[str, ...]  # SAN candidates; the first legal one is used
    done_any: tuple[str, ...]  # "square:piece" - the step is finished if any of these is on the board ("g3:P")
    why: str

    def is_done(self, board: chess.Board) -> bool:
        for token in self.done_any:
            negate = token.startswith("!")  # "!c5:p" is finished once that piece has left the square
            square, symbol = token.lstrip("!").split(":")
            piece = board.piece_at(chess.parse_square(square))
            present = piece is not None and piece.symbol() == symbol
            if present != negate:
                return True
        return False

    def candidates(self, board: chess.Board) -> list[chess.Move]:
        found = []
        for san in self.moves:
            try:
                found.append(board.parse_san(san))
            except ValueError:
                continue
        return found


@dataclass(frozen=True)
class Line:
    name: str
    moves: str  # SAN tokens, space separated
    notes: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BookMove:
    move: chess.Move
    san: str
    note: str
    line: str


@dataclass(frozen=True)
class System:
    id: str
    name: str
    color: bool
    tagline: str
    entry: tuple[str, ...]  # the first move(s) by White this system is meant for ("" = any)
    ideas: tuple[str, ...]
    middlegame: tuple[str, ...]
    endgame: tuple[str, ...]
    setup: tuple[SetupStep, ...]
    lines: tuple[Line, ...]

    # ---- book
    def _index(self):
        cached = _INDEX.get(self.id)
        if cached is None:
            cached = _build_index(self)
            _INDEX[self.id] = cached
        return cached

    def applies(self, board: chess.Board) -> bool:
        """False once White's first move shows this game is not one the system is for (e.g. 1.d4 vs a Caro-Kann)."""
        if not self.entry or not board.move_stack:
            return True
        first = chess.Board().san(board.move_stack[0])
        return first in self.entry

    def book_move(self, board: chess.Board) -> BookMove | None:
        hits = self._index()["mine"].get(board.epd())
        return hits[0] if hits else None

    def in_book(self, board: chess.Board) -> str | None:
        """Name of the line this exact position belongs to, or None if it left the known lines."""
        return self._index()["tree"].get(board.epd())

    def line_for_reply(self, board_before: chess.Board, move: chess.Move) -> str | None:
        """If `move` is the expected reply of some line from this position, that line's name."""
        return self._index()["expected"].get((board_before.epd(), move.uci()))

    def reply_note(self, board_before: chess.Board, move: chess.Move) -> str | None:
        """What the line says about this opponent move, if it is one the system knows."""
        return self._index()["opp_notes"].get((board_before.epd(), move.uci()))

    def _as_mover(self, board: chess.Board) -> chess.Board:
        """The same position with this system's side to move (to see which setup moves are available)."""
        if board.turn == self.color:
            return board
        clone = board.copy(stack=False)
        clone.turn = self.color
        clone.ep_square = None
        return clone

    def next_setup(self, board: chess.Board) -> list[tuple[SetupStep, list[chess.Move]]]:
        board = self._as_mover(board)
        out = []
        for step in self.setup:
            if step.is_done(board):
                continue
            moves = [m for m in step.candidates(board)]
            if moves:
                out.append((step, moves))
        return out

    def setup_complete(self, board: chess.Board) -> bool:
        board = self._as_mover(board)
        return all(step.is_done(board) or not step.candidates(board) for step in self.setup)

    def step_for(self, board: chess.Board, move: chess.Move) -> SetupStep | None:
        for step in self.setup:
            if not step.is_done(board) and move in step.candidates(board):
                return step
        return None


_INDEX: dict[str, dict] = {}


def _build_index(system: System) -> dict:
    mine: dict[str, list[BookMove]] = {}
    tree: dict[str, str] = {}
    expected: dict[tuple[str, str], str] = {}
    opp_notes: dict[tuple[str, str], str] = {}
    for line in system.lines:
        board = chess.Board()
        for ply, san in enumerate(line.moves.split()):
            before = board.epd()
            move = board.parse_san(san)
            mover_is_me = (ply % 2 == 0) == (system.color == WHITE)
            note = line.notes.get(ply, "")
            if mover_is_me:
                if not note:
                    step = system.step_for(board, move)
                    note = step.why if step else f"The usual move in the {line.name}."
                book = BookMove(move, board.san(move), note, line.name)
                existing = mine.setdefault(before, [])
                if all(item.move != move for item in existing):
                    existing.append(book)
            else:
                expected.setdefault((before, move.uci()), line.name)
                if note:
                    opp_notes.setdefault((before, move.uci()), note)
            board.push(move)
            tree.setdefault(board.epd(), line.name)
    return {"mine": mine, "tree": tree, "expected": expected, "opp_notes": opp_notes}


def _s(moves: str, done: str, why: str) -> SetupStep:
    return SetupStep(tuple(moves.split("/")), tuple(done.split()), why)


# --------------------------------------------------------------------------------------- English
ENGLISH = System(
    id="english",
    name="English Opening",
    color=WHITE,
    tagline="Flexible and strategic: fight for d5 from the flank, fianchetto, and keep your options open.",
    entry=(),
    ideas=(
        "1.c4 fights for the d5 square from the side, without committing your centre pawns yet.",
        "Typical setup: Nc3, Nf3, g3, Bg2, castle kingside, then d3 (or d4). The Bg2 rules the long diagonal.",
        "Against 1...e5 it is a Sicilian Defence with colours reversed: you are a move up, so play with a Sicilian mindset.",
    ),
    middlegame=(
        "Expand on the queenside with a3, Rb1 and b4: space, and the b-file for your rook.",
        "Keep the Bg2 open on the long diagonal: pressure on d5 and b7. Avoid blocking it with e4 unless you mean it.",
        "Prepare a central break (d4, or e4 and f4) once your pieces are developed. Do not rush it.",
        "If Black plays ...e6 and ...c5, the hole on d5 is yours: aim a knight there.",
    ),
    endgame=(
        "The fianchetto bishop and queenside space make endgames pleasant: create a passed pawn on the b- or c-file.",
        "Bring the king toward the centre and trade the pieces that restrict your Bg2.",
    ),
    setup=(
        _s("c4", "c4:P", "c4 claims space and fights for d5 without committing your centre."),
        _s("Nc3", "c3:N", "Nc3 adds pressure on d5 and supports a later e4."),
        _s("Nf3", "f3:N", "Nf3 develops the knight and controls e5 and d4."),
        _s("g3", "g3:P", "g3 prepares the fianchetto: the bishop will live on g2."),
        _s("Bg2", "g2:B", "Bg2 puts the bishop on the long diagonal, hitting d5 and b7."),
        _s("O-O", "g1:K", "Castle to tuck the king away and connect the rooks."),
        _s("d3", "d3:P d4:P", "d3 supports the centre and the Nc3 while keeping the Bg2 strong. d4 is the alternative."),
        _s("Rb1", "b1:R", "Rb1 prepares b4, the queenside space-gaining advance."),
        _s("a3", "a3:P a4:P", "a3 prepares b4 and stops ...Bb4 or ...Nb4."),
        _s("b4", "b4:P b5:P", "b4 gains space on the queenside and opens the b-file."),
    ),
    lines=(
        Line("Reversed Sicilian (vs 1...e5)", "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5 Bg2 Nb6 O-O Be7 d3 O-O Be3", {
            0: "1.c4: the English. It stakes a claim on d5 from the flank and keeps your centre flexible.",
            1: "Black plays ...e5, grabbing the centre. This is a Reversed Sicilian: you have an extra tempo, so play with a Sicilian mindset.",
            2: "Nc3 piles pressure on d5 and supports a later e4 or d5-hole ideas.",
            4: "Nf3 develops and hits the e5 pawn.",
            6: "g3 prepares Bg2, the signature English bishop.",
            7: "Black strikes in the centre with ...d5. Meet it by capturing.",
            8: "cxd5 opens the diagonal for your future Bg2 and wins a tempo against the recapturing knight.",
            10: "Bg2 attacks the knight on d5 and eyes b7.",
            12: "Castle: the king is safe and the rook is ready for the centre.",
            14: "d3 is solid: it protects the centre and keeps the Bg2 powerful.",
            16: "Be3 develops your last minor piece, eyeing c5 and a7, and prepares Rc1 or Qd2.",
        }),
        Line("Reversed Sicilian, sharp 4...Bb4", "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 Bb4 Bg2 O-O O-O e4 Ng5 Bxc3 dxc3 h6 Nh3 d6", {
            7: "Black pins the knight. Do not panic: just develop and castle.",
            12: "Ng5 attacks the e4 pawn that Black pushed. Look for targets when Black overextends.",
            14: "You take back with the d-pawn: your bishop pair and open lines compensate for the doubled pawns.",
            16: "Nh3 keeps the knight alive and heads toward f4.",
        }),
        Line("Symmetrical English (vs 1...c5)", "c4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 Nf3 e6 O-O Nge7 d3 O-O a3", {
            1: "Black copies you. In the Symmetrical English the plan is slow: develop, fianchetto, then expand on the queenside.",
            14: "a3 prepares Rb1 and b4. Black will play on the other wing; this is a race of plans.",
        }),
        Line("vs 1...Nf6 (Queen's Gambit setups)", "c4 Nf6 Nc3 e6 Nf3 d5 d4 Be7 Bg5 h6 Bh4 O-O e3", {
            6: "d4 transposes into a Queen's Gambit Declined. The English is flexible: you may enter other openings on your terms.",
        }),
        Line("vs 1...e6", "c4 e6 Nc3 d5 d4 Nf6 Nf3 Be7 Bg5 O-O e3 h6 Bh4", {
            4: "d4 transposes into a Queen's Gambit Declined, a solid and classical structure.",
        }),
        Line("vs 1...c6 (Slav-type)", "c4 c6 Nf3 d5 e3 Nf6 Nc3 e6 d4 Nbd7", {
            4: "e3 keeps the position solid and flexible: a Semi-Slav structure is coming.",
        }),
        Line("vs 1...g6", "c4 g6 Nc3 Bg7 e4 d6 d4 Nf6 Nf3 O-O Be2", {
            4: "Against the fianchetto, take the centre: e4 and d4 give you space.",
        }),
        Line("vs 1...d5", "c4 d5 cxd5 Qxd5 Nc3 Qd8 e4 Nf6 Nf3", {
            2: "Take the pawn: Black's queen comes out early and you gain time with Nc3.",
            6: "e4 builds a strong centre while Black's queen has lost time.",
        }),
        Line("vs 1...Nf6 2.Nc3 d5 (Reversed Grunfeld)", "c4 Nf6 Nc3 d5 cxd5 Nxd5 g3 g6 Bg2 Nb6 Nf3 Bg7 O-O O-O d3", {
            4: "Capture on d5 to open the c-file and the long diagonal.",
            8: "Bg2 is the star piece again: the long diagonal is wide open.",
        }),
    ),
)

# ---------------------------------------------------------------------------------------- London
LONDON = System(
    id="london",
    name="London System",
    color=WHITE,
    tagline="One setup against everything: d4, Nf3, Bf4, e3, c3. Easy to learn, rich in plans.",
    entry=(),
    ideas=(
        "Play the same pieces every game: pawns on d4, e3 and c3, bishop out on f4, knights on f3 and d2.",
        "Develop the c1 bishop BEFORE playing e3, otherwise it gets locked in.",
        "Your structure is solid; Black has to find a plan to hurt you.",
    ),
    middlegame=(
        "Aim a knight at e5: it is a great outpost supported by the d4 pawn.",
        "The bishop on d3 points at h7: combine it with Ne5 and Qf3 or Qh5 against a castled king.",
        "Break in the centre with c4 or e4 once all your pieces are developed.",
        "If Black plays ...Qb6, defend b2 calmly with Qb3 or Qc1; do not panic.",
    ),
    endgame=(
        "Your pawn structure is healthy; trade pieces and use an active king.",
        "Watch the light-squared bishop on f4: it is often better than a knight when pawns are on both sides.",
    ),
    setup=(
        _s("d4", "d4:P", "d4 takes space in the centre."),
        _s("Nf3", "f3:N", "Nf3 develops and covers e5 and d4."),
        _s("Bf4", "f4:B", "Bf4 develops the bishop outside the pawn chain BEFORE e3 locks it in."),
        _s("e3", "e3:P", "e3 supports d4 and opens the f1 bishop."),
        _s("c3", "c3:P", "c3 supports the d4 pawn and gives the queen the b3 square."),
        _s("Nbd2", "d2:N", "Nbd2 develops the last knight and heads for e5 or f3-g5 ideas."),
        _s("Bd3", "d3:B", "Bd3 points at h7 and the kingside."),
        _s("O-O", "g1:K", "Castle to finish development."),
        _s("h3", "h3:P", "h3 gives your bishop on f4 a retreat on h2 and stops ...Bg4."),
    ),
    lines=(
        Line("London vs 1...d5", "d4 d5 Nf3 Nf6 Bf4 e6 e3 c5 c3 Nc6 Nbd2 Bd6 Bg3 O-O Bd3", {
            0: "1.d4: you will build the London setup whatever Black does.",
            4: "Bf4 comes out before e3: the signature London move.",
            6: "e3 supports d4 and frees your king's bishop.",
            8: "c3 makes the centre solid and prepares Qb3 if needed.",
            12: "Bg3 offers the bishop trade: after Bxg3 you recapture hxg3 or fxg3, getting an open file.",
            14: "Bd3 completes the classic London pyramid: pawns d4-e3-c3, bishops f4/g3 and d3.",
        }),
        Line("London vs the King's Indian setup", "d4 Nf6 Nf3 g6 Bf4 Bg7 e3 O-O Be2 d6 h3 Nbd7 O-O", {
            6: "e3 still comes after Bf4. Against a fianchetto, Be2 and h3 are a sound, patient setup.",
        }),
        Line("London vs the ...Qb6 trick", "d4 d5 Bf4 c5 e3 Nc6 c3 Nf6 Nf3 Qb6 Qb3 c4 Qxb6 axb6 Nbd2 Bf5 Be2 e6", {
            10: "Black attacks b2. Qb3 is the calm answer: if queens come off, your structure is fine.",
            12: "Qxb6 axb6 gives Black doubled b-pawns but an open a-file: develop with Nbd2 and be patient.",
        }),
        Line("London vs 1...e6", "d4 e6 Nf3 d5 Bf4 c5 e3 Nc6 c3 Nf6 Nbd2 Bd6 Bg3", {}),
    ),
)

# ------------------------------------------------------------------------------------- Italian
ITALIAN = System(
    id="italian",
    name="Italian Game (Giuoco Pianissimo)",
    color=WHITE,
    tagline="Classical and slow-burning: develop, castle, play c3 and d3, then build up with d4.",
    entry=("e4",),
    ideas=(
        "Put the bishop on c4 where it eyes f7, develop the knights and castle quickly.",
        "The quiet plan (Pianissimo): c3 and d3, Re1, Bb3, h3 and Nbd2-f1-g3, then the central break d4.",
        "Do not rush d4: first make sure your pieces are ready and your bishop has a safe retreat on b3.",
    ),
    middlegame=(
        "The break d4 (after c3 and d3 are in) opens the centre when you are better developed.",
        "Reroute the queen's knight: Nbd2, then f1 and g3 or e3, heading for the kingside.",
        "Keep the bishop pair; if Black pins with ...Bg4 or ...h6/...Bg4 ideas, h3 asks the question.",
    ),
    endgame=(
        "Open-centre endgames favour the side with the more active king and rooks: centralise early.",
        "If you get a pawn majority in the centre, make a passed pawn.",
    ),
    setup=(
        _s("e4", "e4:P", "e4 grabs the centre and opens lines for your bishop and queen."),
        _s("Nf3", "f3:N", "Nf3 develops with a threat on e5."),
        _s("Bc4", "c4:B", "Bc4 develops the bishop to its best diagonal, aiming at f7."),
        _s("c3", "c3:P", "c3 prepares d4 and gives your bishop a retreat later."),
        _s("d3", "d3:P d4:P", "d3 is the quiet, solid choice: it supports e4 and the c4 bishop."),
        _s("O-O", "g1:K", "Castle to safety and connect the rooks."),
        _s("Re1", "e1:R", "Re1 supports the e4 pawn and prepares d4."),
        _s("Bb3", "b3:B", "Bb3 keeps the bishop on the a2-g8 diagonal, out of reach of ...a6/...b5 tricks."),
        _s("h3", "h3:P", "h3 stops ...Bg4 so the knight on f3 is not pinned."),
        _s("Nbd2", "d2:N", "Nbd2 develops the last knight; it is on its way to f1 and g3."),
    ),
    lines=(
        Line("Giuoco Pianissimo", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O Re1 a6 Bb3 Ba7 h3 h6 Nbd2 Re8 Nf1 Be6 Ng3", {
            0: "1.e4: the most principled start. You claim the centre and open lines.",
            4: "Bc4: the Italian bishop, aimed at f7 and ready to be placed on b3 later.",
            6: "c3 prepares d4. It also gives your queen a square on b3 or a4 if needed.",
            8: "d3 is the quiet, 'pianissimo' choice: solid, with long-term pressure.",
            12: "Re1 supports e4 and keeps d4 as a future break.",
            14: "Bb3 steps back before ...b5 can chase it.",
            16: "h3 prevents ...Bg4 and prepares the Nbd2-f1-g3 plan.",
            18: "Nbd2 starts the famous knight tour: d2, f1, g3 (or e3).",
            20: "Nf1 heads for g3, where the knight eyes f5 and h5.",
        }),
        Line("vs the Two Knights (3...Nf6)", "e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Be7 O-O O-O Re1 d6 c3 Na5 Bb3 Nxb3 Qxb3", {
            6: "d3 keeps things calm: you avoid the sharp lines of the Two Knights and play the same quiet plan.",
        }),
        Line("vs 3...Be7", "e4 e5 Nf3 Nc6 Bc4 Be7 d3 Nf6 O-O O-O Re1 d6 c3", {}),
        Line("vs the Petroff", "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3 Nc6 O-O Be7 c4 Nb4 Be2 O-O Nc3 Bf5", {
            4: "Against the Petroff, capture the e5 pawn, then kick the knight back: this is the main line, not the Italian.",
        }),
        Line("vs the Sicilian (Alapin)", "e4 c5 c3 d5 exd5 Qxd5 d4 Nf6 Nf3 Bg4 Be2 e6 O-O Nc6", {
            2: "c3 is the Alapin: you prepare d4 and build a big centre, avoiding the heavy theory of the Open Sicilian.",
        }),
        Line("vs the French (Classical)", "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 e5 Nfd7 Bxe7 Qxe7 f4 O-O Nf3 c5", {}),
    ),
)

# -------------------------------------------------------------------------------- Queen's Gambit
QUEENS_GAMBIT = System(
    id="queens_gambit",
    name="Queen's Gambit",
    color=WHITE,
    tagline="The classical way to fight for the centre: d4 and c4, then pieces to natural squares.",
    entry=("d4",),
    ideas=(
        "c4 offers a pawn to deflect Black's d5 pawn; if Black takes, you win the centre back easily.",
        "Develop with Nc3 and Nf3, put the bishop on g5 or f4, and play e3 to support the centre.",
        "Do not hurry to win the c4 pawn back: develop first.",
    ),
    middlegame=(
        "Minority attack: advance b4-b5 against Black's queenside pawns to create weaknesses.",
        "Break with e4 when you are ready; an e4 push can give you a big central space advantage.",
        "Watch for an isolated pawn on d4 after ...dxc4 and ...c5: it gives you activity.",
    ),
    endgame=(
        "Endgames with a queenside pawn majority are good: create a passed pawn.",
        "In rook endings keep your rooks active, behind passed pawns.",
    ),
    setup=(
        _s("d4", "d4:P", "d4 takes the centre."),
        _s("c4", "c4:P", "c4 is the Queen's Gambit: it pressures Black's d5."),
        _s("Nc3", "c3:N", "Nc3 adds more pressure on d5 and prepares e4."),
        _s("Nf3", "f3:N", "Nf3 develops the knight and protects d4."),
        _s("Bg5/Bf4", "g5:B f4:B", "Develop the bishop outside the pawn chain before e3 closes it in."),
        _s("e3", "e3:P", "e3 supports d4 and opens the f1 bishop."),
        _s("Bd3/Be2", "d3:B e2:B", "Develop the last bishop to a natural square."),
        _s("O-O", "g1:K", "Castle to safety."),
        _s("Rc1", "c1:R", "Rc1 stands on the c-file where the action will be."),
    ),
    lines=(
        Line("Queen's Gambit Declined", "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 Nbd7 Rc1 c6 Bd3 dxc4 Bxc4 Nd5 Bxe7 Qxe7 O-O Nxc3 Rxc3 e5", {
            0: "1.d4: you take space and control e5.",
            2: "c4: the Queen's Gambit. If Black takes, you will win the pawn back.",
            6: "Bg5 pins the knight to the queen-side and increases pressure on d5.",
            8: "e3 supports d4 and opens the way for the f1 bishop.",
            12: "Rc1 pre-empts the c-file: after ...dxc4 you will recapture with the bishop.",
            14: "Bd3 develops to the best diagonal.",
            16: "Take the pawn back when it is safe: Bxc4.",
            18: "Bxe7 relieves the pressure on d5; trade pieces to ease Black's cramped position.",
        }),
        Line("vs the Slav", "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5 e3 e6 Bxc4 Bb4 O-O Nbd7", {
            8: "a4 stops ...b5 so you can win back the c4 pawn.",
            12: "Bxc4: pawn recovered. Good development and the centre are yours.",
        }),
        Line("Queen's Gambit Accepted", "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O a6 Qe2 b5 Bb3 Bb7 Rd1 Nbd7 Nc3 Qb6", {
            3: "Black takes the pawn. Do not worry: develop and recapture with Bxc4 when ready.",
            8: "Bxc4: the pawn is back with the better development.",
        }),
    ),
)

# ------------------------------------------------------------------------------------- Caro-Kann
CARO_KANN = System(
    id="caro_kann",
    name="Caro-Kann Defence",
    color=BLACK,
    tagline="Rock-solid against 1.e4: ...c6 and ...d5, develop the light bishop BEFORE ...e6.",
    entry=("e4",),
    ideas=(
        "Meet 1.e4 with ...c6 and ...d5: you challenge the centre while keeping a very solid pawn structure.",
        "Get the light-squared bishop out (usually to f5 or g4) BEFORE you play ...e6.",
        "Trade the light-squared bishops when you can: it removes White's most dangerous attacker.",
    ),
    middlegame=(
        "Strike back in the centre with ...c5 (or sometimes ...e5) when your pieces are developed.",
        "Your queenside is healthy: aim for good endgames; you rarely have weaknesses.",
        "Be careful on the kingside against White's h4-h5 attack in the Classical line: ...h6 and ...Bh7 fix it.",
    ),
    endgame=(
        "Your healthy pawn structure makes endgames comfortable: look for a favourable bishop-versus-knight position.",
        "Create a passed pawn from your central majority and activate the king.",
    ),
    setup=(
        _s("c6", "c6:p", "...c6 prepares ...d5 and keeps the position solid."),
        _s("d5", "d5:p", "...d5 challenges White's centre."),
        _s("Bf5/Bg4", "f5:b g4:b", "Develop the light bishop OUTSIDE the pawn chain before ...e6 closes it in."),
        _s("e6", "e6:p", "...e6 completes a sturdy centre."),
        _s("Nf6", "f6:n", "...Nf6 develops with pressure on the centre."),
        _s("Nd7", "d7:n", "...Nd7 supports ...e5 or ...c5 and does not block the bishop."),
        _s("Be7", "e7:b", "...Be7 prepares castling."),
        _s("O-O", "g8:k", "Castle to safety."),
        _s("c5", "c5:p", "...c5 is the typical freeing break."),
    ),
    lines=(
        Line("Classical Caro-Kann", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6 Nf3 Nd7 h5 Bh7 Bd3 Bxd3 Qxd3 e6 Bf4 Ngf6 O-O-O Be7", {
            1: "...c6: the Caro-Kann. It prepares ...d5 without blocking your c8 bishop.",
            3: "...d5 challenges the centre.",
            5: "...dxe4 clears the centre and wins a pawn temporarily.",
            7: "...Bf5: the key idea of the system, the bishop comes out BEFORE ...e6.",
            9: "...Bg6 keeps the bishop safe and keeps the diagonal.",
            11: "...h6 answers White's h4-h5 plan, giving the bishop on g6 the h7 square.",
            13: "...Nd7 prepares ...Ngf6 and ...e5 without blocking the bishop.",
            15: "...Bh7 retreats the bishop to a safe diagonal.",
            17: "...Bxd3: trade the light-squared bishops, White's most dangerous piece.",
            19: "...e6: now the centre is solid and the bishop is already traded or developed.",
            21: "...Ngf6 develops, trading White's active knight.",
            23: "...Be7 prepares castling.",
        }),
        Line("Advance Variation", "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 Be3 cxd4 Nxd4", {
            9: "...c5 attacks White's pawn chain at its base: the classic counter.",
        }),
        Line("Exchange Variation", "e4 c6 d4 d5 exd5 cxd5 c4 Nf6 Nc3 e6 Nf3 Be7", {
            9: "...e6 supports d5 and keeps the structure sound.",
        }),
        Line("Two Knights", "e4 c6 Nc3 d5 Nf3 Bg4 h3 Bxf3 Qxf3 e6 d3 Nf6", {
            5: "...Bg4: the bishop comes out before ...e6, as always in the Caro-Kann.",
        }),
    ),
)

# --------------------------------------------------------------------------------------- Sicilian
SICILIAN = System(
    id="sicilian",
    name="Sicilian Defence",
    color=BLACK,
    tagline="The fighting reply to 1.e4: unbalance the position with ...c5 and play for a win.",
    entry=("e4",),
    ideas=(
        "...c5 fights for the centre from the flank and gives you an asymmetrical position.",
        "After 2.Nf3 d6 3.d4 cxd4 4.Nxd4 Nf6 5.Nc3, play ...a6 (Najdorf): it stops Nb5 and prepares ...b5 and ...e5.",
        "You have a healthy extra central pawn after ...cxd4: use it with ...e5 or ...e6 and active pieces.",
    ),
    middlegame=(
        "Queenside play: ...b5, ...Bb7 and ...Rc8 pressure the c-file and White's queenside.",
        "If White attacks on the kingside, counterattack with ...b5-b4 and ...Qc7/...Rc8: speed is everything.",
        "Keep the d6 pawn protected; the hole on d5 can be a problem if you play ...e5.",
    ),
    endgame=(
        "Your queenside majority can become a passed pawn: trade queens and push it.",
        "Activate the king and place rooks on open files.",
    ),
    setup=(
        _s("c5", "c5:p", "...c5 fights for the centre from the side."),
        _s("d6", "d6:p", "...d6 supports e5 and prepares ...Nf6."),
        _s("Nf6", "f6:n", "...Nf6 develops and attacks e4."),
        _s("cxd4", "!c5:p", "Take on d4 to open the c-file and trade a wing pawn for a centre pawn."),
        _s("a6", "a6:p", "...a6 prepares ...b5 and stops Nb5."),
        _s("e5/e6", "e5:p e6:p", "...e5 or ...e6 builds the centre."),
        _s("Be7/Be6", "e7:b e6:b", "Develop the bishop to e7, or to e6 against a Be3 setup."),
        _s("O-O", "g8:k", "Castle to safety."),
        _s("b5", "b5:p", "...b5 gains space on the queenside and starts counterplay."),
    ),
    lines=(
        Line("Najdorf vs the English Attack", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6 f3 Nbd7 Qd2 b5", {
            1: "...c5: the Sicilian. You will have an asymmetrical position full of chances.",
            3: "...d6 prepares ...Nf6 without allowing e5.",
            5: "...cxd4 trades a flank pawn for a centre pawn.",
            9: "...a6: the Najdorf. It stops Nb5, prepares ...b5, and keeps options with ...e5 or ...e6.",
            11: "...e5 gains space and kicks the knight away. White's Be3/f3/Qd2 set-up is the English Attack.",
            13: "...Be6 develops with pressure on White's queenside.",
            17: "...b5 is the thematic break: you gain space and attack.",
        }),
        Line("Najdorf, quiet 6.Be2", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be2 e5 Nb3 Be7 O-O O-O", {
            11: "...e5 in the Najdorf: solid, with the d5 hole to watch.",
        }),
        Line("Najdorf, 6.Bg5", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Bg5 e6 f4 Be7 Qf3 Qc7 O-O-O Nbd7", {
            11: "...e6 against Bg5: the Scheveningen-style structure, where you keep a compact pawn centre.",
        }),
        Line("Alapin (2.c3)", "e4 c5 c3 d5 exd5 Qxd5 d4 Nf6 Nf3 Bg4 Be2 e6 O-O Nc6", {
            3: "...d5 meets the Alapin in the centre: you equalise at once.",
        }),
        Line("Closed (2.Nc3)", "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6", {}),
    ),
)

# ----------------------------------------------------------------------------------- King's Indian
KINGS_INDIAN = System(
    id="kings_indian",
    name="King's Indian Defence",
    color=BLACK,
    tagline="Hypermodern and ambitious: let White take the centre, then attack it and the king.",
    entry=("d4", "c4", "Nf3"),
    ideas=(
        "Fianchetto your king's bishop (...g6, ...Bg7), castle, and let White build a big centre.",
        "Then strike with ...e5 (or ...c5): your bishop on g7 becomes a monster when the centre opens.",
        "In the main lines, attack the king with ...f5 and a kingside pawn storm while White attacks on the queenside.",
    ),
    middlegame=(
        "When White plays d5, play ...Ne7 and ...f5: start the kingside pawn storm.",
        "Keep your Bg7 alive: try not to let it be blocked by a pawn on e5.",
        "If the centre locks, count the race: your kingside attack against White's queenside play.",
    ),
    endgame=(
        "Your pieces are active but your king can be exposed: trade queens when your attack runs out.",
        "A queenside pawn majority or a protected passed pawn decides most endgames.",
    ),
    setup=(
        _s("Nf6", "f6:n", "...Nf6 develops and watches e4 and d5."),
        _s("g6", "g6:p", "...g6 prepares the fianchetto."),
        _s("Bg7", "g7:b", "...Bg7 places the bishop on the long diagonal, aimed at the centre."),
        _s("d6", "d6:p", "...d6 supports ...e5 and covers the dark squares."),
        _s("O-O", "g8:k", "Castle early: the king belongs behind the fianchetto."),
        _s("e5", "e5:p", "...e5 is the main central strike."),
        _s("Nc6/Nbd7", "c6:n d7:n", "Develop the last knight to support ...e5."),
        _s("f5", "f5:p", "...f5 starts the kingside attack after the centre closes."),
    ),
    lines=(
        Line("Classical King's Indian", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6 d5 Ne7 Ne1 Nd7 Be3 f5", {
            1: "...Nf6: flexible, it pressures e4 and d5.",
            3: "...g6 prepares the fianchetto.",
            5: "...Bg7: the bishop on the long diagonal.",
            7: "...d6 supports e5 and controls the dark squares.",
            9: "...O-O: castle early.",
            11: "...e5: the main central strike.",
            13: "...Nc6 pressures d4.",
            15: "...Ne7 heads for the kingside and prepares ...f5.",
            17: "...Nd7 supports the ...f5 pawn storm.",
            19: "...f5: the classic King's Indian attack begins.",
        }),
        Line("King's Indian vs the Fianchetto", "d4 Nf6 c4 g6 g3 Bg7 Bg2 O-O Nc3 d6 Nf3 Nbd7 O-O e5 e4 c6", {}),
        Line("King's Indian vs the Saemisch", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 f3 O-O Be3 Nc6 Qd2 a6", {
            11: "...Nc6 pressures d4; ...a6 prepares ...Rb8 and ...b5.",
        }),
        Line("King's Indian vs the London", "d4 Nf6 Bf4 g6 Nf3 Bg7 e3 O-O Be2 d6 h3 Nbd7 O-O c5", {}),
    ),
)


SYSTEMS: dict[str, System] = {s.id: s for s in (ENGLISH, LONDON, ITALIAN, QUEENS_GAMBIT, CARO_KANN, SICILIAN, KINGS_INDIAN)}


def get_system(system_id: str | None) -> System | None:
    return SYSTEMS.get(system_id or "")


# ------------------------------------------------------------------------------------- game phases
PIECE_POINTS = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def phase(board: chess.Board, setup_done: bool) -> str:
    material = sum(
        PIECE_POINTS.get(piece.piece_type, 0) for piece in board.piece_map().values()
    )  # starting value is 62
    queens = bool(board.queens)
    if not queens and material <= 40 or material <= 24:
        return "endgame"
    if not setup_done and board.fullmove_number <= 14:
        return "opening"
    return "middlegame"


def endgame_tip(board: chess.Board) -> str:
    """One general endgame principle that fits the position."""
    pieces = board.piece_map().values()
    kinds = {p.piece_type for p in pieces if p.piece_type not in (chess.PAWN, chess.KING)}
    if not kinds:
        return "Pawn endgame: the king is a fighting piece. Use the opposition, and an outside passed pawn can decide the game."
    if kinds == {chess.ROOK}:
        return "Rook endgame: keep your rook active, put it behind passed pawns and cut off the enemy king. Passive rooks lose."
    if kinds == {chess.QUEEN}:
        return "Queen endgame: watch for perpetual check and keep your king safe; a passed pawn supported by the queen is strong."
    if kinds <= {chess.KNIGHT, chess.BISHOP}:
        return "Minor-piece endgame: activate your king, put pawns on the colour opposite your bishop, and place knights on strong outposts."
    return "Endgame: activate your king, trade into a favourable structure and create a passed pawn."
