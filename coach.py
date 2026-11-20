"""Turns engine output, opening knowledge and tactics into short, plain-language advice."""

import re
from dataclasses import dataclass, field

import chess

import tactics
from engine import Engine, Line
from openings import OpeningBook

CP_CLAMP = 1000
SAN_MARKER = re.compile(r"<<([^>]+)>>")
PIECE_SPEECH = {"N": "Knight", "B": "Bishop", "R": "Rook", "Q": "Queen", "K": "King"}


def speak_san(san: str) -> str:
    """Make a SAN move readable by a text-to-speech engine."""
    core = san.rstrip("+#")
    suffix = " checkmate" if san.endswith("#") else " check" if san.endswith("+") else ""
    if core.startswith("O-O-O"):
        return "castle queenside" + suffix
    if core.startswith("O-O"):
        return "castle kingside" + suffix
    out = ""
    if core and core[0] in PIECE_SPEECH:
        out = PIECE_SPEECH[core[0]] + " "
        core = core[1:]
    promotion = ""
    if "=" in core:
        core, piece = core.split("=")
        promotion = f" promotes to {PIECE_SPEECH.get(piece, piece).lower()}"
    out += core.replace("x", " takes ")
    return " ".join(out.split()) + promotion + suffix


def render(text: str, speech: bool = False) -> str:
    return SAN_MARKER.sub(lambda m: speak_san(m.group(1)) if speech else m.group(1), text)


def san_marker(san: str) -> str:
    return f"<<{san}>>"


@dataclass
class Advice:
    parts: list[str] = field(default_factory=list)
    detail: list[str] = field(default_factory=list)
    best_move: chess.Move | None = None  # the move to draw on the board, when it is the user's turn
    lines: list[dict] = field(default_factory=list)  # engine lines for a UI: san, score text, cp, pv
    grade: str | None = None  # quality of the user's last move: best / good / playable / mistake / blunder
    best_move_hidden: chess.Move | None = None  # the move behind Practice/Test prompts (shown only on Hint)
    plan_title: str = ""  # trainer: heading and bullet points of the current plan card
    plan: list[str] = field(default_factory=list)
    progress: tuple[int, int] | None = None  # trainer: setup steps done / total
    phase: str = ""  # opening / middlegame / endgame

    @property
    def text(self) -> str:
        return render(" ".join(self.parts))

    @property
    def speech(self) -> str:
        return render(" ".join(self.parts), speech=True)


def _clamp(cp: int) -> int:
    return max(-CP_CLAMP, min(CP_CLAMP, cp))


def _eval_category(cp: int) -> int:
    if cp >= 300:
        return 2
    if cp >= 100:
        return 1
    if cp > -100:
        return 0
    if cp > -300:
        return -1
    return -2


EVAL_SENTENCES = {
    2: "You're clearly winning.",
    1: "You're a little better.",
    0: "The position is about equal.",
    -1: "You're a little worse, so stay sharp.",
    -2: "You're in trouble, but keep fighting - look for tricks.",
}


class Coach:
    def __init__(self, engine: Engine, book: OpeningBook, user_color: bool):
        self.engine = engine
        self.book = book
        self.user_color = user_color
        self._cache: dict[str, list[Line]] = {}
        self._announced: set[str] = set()
        self._plan_said: set[str] = set()
        self._last_eval_category: int | None = None
        self.grades: dict[int, tuple[str, int]] = {}  # ply -> (grade, centipawn loss) of the user's moves

    def reset(self) -> None:
        self._announced.clear()
        self._plan_said.clear()
        self._last_eval_category = None
        self.grades.clear()

    def forget_after(self, ply_count: int) -> None:
        """Drop grades for moves that were taken back (keep plies 1..ply_count)."""
        for ply in [p for p in self.grades if p > ply_count]:
            del self.grades[ply]

    def analyse(self, board: chess.Board) -> list[Line]:
        key = board.epd()
        if key not in self._cache:
            self._cache[key] = self.engine.analyse(board)
        return self._cache[key]

    def advise(self, board: chess.Board, new_moves: int = 1) -> Advice:
        """Advice after move(s) have been entered (or at the start of the game).

        `new_moves` is how many plies were just played (the camera can see two at once);
        each one gets feedback."""
        advice = Advice()
        if board.is_game_over(claim_draw=True):
            advice.parts.append(self._game_over_sentence(board))
            return advice

        count = min(max(new_moves, 1), len(board.move_stack))
        if count:
            replay = board.copy()
            played = [replay.pop() for _ in range(count)][::-1]
            for move in played:
                after = replay.copy()
                after.push(move)
                feedback = self._feedback(replay, after, move)
                if feedback:
                    advice.parts.append(feedback)
                if len(after.move_stack) in self.grades:
                    advice.grade = self.grades[len(after.move_stack)][0]
                replay = after

        user_turn = board.turn == self.user_color
        advice.parts.extend(self._opening_sentences(board, user_turn))
        if user_turn:
            advice.parts.extend(self._threat_sentences(board))
            advice.parts.extend(self.suggestion(board, advice))
        elif board.move_stack:
            advice.parts.append("Now wait for your opponent's reply, and I'll suggest your next move.")
        return advice

    def hint(self, board: chess.Board) -> Advice:
        advice = Advice()
        if board.is_game_over(claim_draw=True):
            advice.parts.append(self._game_over_sentence(board))
        elif board.turn != self.user_color:
            advice.parts.append("It's your opponent's turn. I'll suggest your move as soon as they've played.")
        else:
            advice.parts.extend(self.suggestion(board, advice, always_eval=True))
        return advice

    def _game_over_sentence(self, board: chess.Board) -> str:
        outcome = board.outcome(claim_draw=True)
        if outcome is None or outcome.winner is None:
            reason = outcome.termination.name.replace("_", " ").lower() if outcome else "draw"
            return f"The game is a draw by {reason}."
        if outcome.winner == self.user_color:
            if outcome.termination == chess.Termination.CHECKMATE:
                return "Checkmate! You won. Great game!"
            return "You won. Great game!"
        return "Checkmate. You lost this one, but good fight." if (
            outcome.termination == chess.Termination.CHECKMATE
        ) else "You lost this one, but good fight."

    def _feedback(self, before: chess.Board, after: chess.Board, move: chess.Move) -> str | None:
        mover = before.turn
        before_lines = self.analyse(before)
        after_lines = self.analyse(after)
        if not before_lines or not after_lines:
            return None
        best = before_lines[0]
        best_cp = _clamp(best.cp(mover))
        after_cp = _clamp(after_lines[0].cp(mover))
        loss = max(0, best_cp - after_cp)
        is_best = move == best.move

        if mover != self.user_color:
            if loss >= 300:
                return "Your opponent just blundered! Look for a way to punish it."
            if loss >= 150:
                return "Your opponent's last move was a mistake. Look for a way to take advantage."
            return None

        best_san = san_marker(best.san)
        ply = len(after.move_stack)
        if is_best:
            self.grades[ply] = ("best", 0)
            return "Excellent, that's the engine's top choice."
        if loss < 70:
            self.grades[ply] = ("good", loss)
            return "Good move."
        if loss < 150:
            self.grades[ply] = ("playable", loss)
            return f"That's playable, but {best_san} was a little stronger."
        extra = self._consequence(after, after_lines[0])
        if loss < 300:
            self.grades[ply] = ("mistake", loss)
            return f"That was a mistake. {best_san} was better.{extra}"
        self.grades[ply] = ("blunder", loss)
        return f"Ouch, that's a blunder. {best_san} was much stronger.{extra}"

    def _consequence(self, after: chess.Board, reply: Line) -> str:
        mate = reply.mate(self.user_color)
        if mate is not None:
            return f" Now your opponent has checkmate in {-mate}." if mate < 0 else ""
        if after.is_capture(reply.move):
            victim = after.piece_at(reply.move.to_square)
            if victim is not None and victim.color == self.user_color:
                return (
                    f" Now they can take your {tactics.NAMES[victim.piece_type]} "
                    f"on {chess.square_name(reply.move.to_square)}."
                )
        return ""

    def _opening_sentences(self, board: chess.Board, user_turn: bool) -> list[str]:
        match = self.book.identify(board)
        if match is None or board.fullmove_number > 15:
            return []
        gap = len(board.move_stack) - match.ply
        if gap > 2:
            return []
        opening = match.opening
        out = []
        if opening.name not in self._announced:
            self._announced.add(opening.name)
            out.append(f"That's the {opening.name}.")
        if user_turn and opening.name not in self._plan_said:
            self._plan_said.add(opening.name)
            out.append(opening.plan_for(self.user_color))
            if opening.trap:
                out.append(opening.trap)
        return out

    def _threat_sentences(self, board: chess.Board) -> list[str]:
        user = self.user_color
        out = []
        for square in tactics.hanging_pieces(board, user)[:2]:
            name = tactics.describe(board, square)
            if board.attackers(user, square):
                out.append(f"Careful, your {name} can be won by a smaller piece.")
            else:
                out.append(f"Careful, your {name} is under attack and unprotected.")
        for san, motif in tactics.fork_threats(board, user)[:1]:
            out.append(f"Watch out, your opponent threatens {san_marker(san)}, which {motif.text}.")
        if len(out) < 2:
            for square in tactics.pinned_pieces(board, user)[:1]:
                out.append(f"Your {tactics.describe(board, square)} is pinned to your king, so it can't move freely.")
        return out[:3]

    def suggestion(self, board: chess.Board, advice: Advice, always_eval: bool = False) -> list[str]:
        lines = self.analyse(board)
        if not lines:
            return []
        top = lines[0]
        advice.best_move = top.move
        user = self.user_color
        out = []

        mate = top.mate(user)
        if mate is not None and mate > 0:
            out.append(f"You have checkmate in {mate}! Play {san_marker(top.san)}.")
        else:
            out.append(f"Consider {san_marker(top.san)}. {self._explain(board, top)}")
            category = _eval_category(top.cp(user))
            if always_eval or category != self._last_eval_category:
                out.append(EVAL_SENTENCES[category])
            self._last_eval_category = category

        for line in lines:
            score = line.score.pov(user)
            shown = f"mate in {abs(score.mate())}" if score.is_mate() else f"{score.score() / 100:+.2f}"
            advice.detail.append(f"  {line.san:<8} {shown:>10}   {' '.join(line.pv_san)}")
            advice.lines.append({
                "san": line.san, "score": shown, "cp": line.cp(user), "pv": " ".join(line.pv_san),
                "uci": line.move.uci(),
            })
        return out

    def _explain(self, board: chess.Board, line: Line) -> str:
        move = line.move
        reasons: list[str] = []
        piece_type = board.piece_type_at(move.from_square)
        after = board.copy(stack=False)
        after.push(move)

        if after.is_checkmate():
            return "It's checkmate."

        if board.is_capture(move):
            if board.is_en_passant(move):
                reasons.append("captures a pawn en passant")
            else:
                victim_type = board.piece_type_at(move.to_square)
                victim = tactics.NAMES[victim_type]
                square = chess.square_name(move.to_square)
                if not board.attackers(not board.turn, move.to_square):
                    reasons.append(f"wins a free {victim} on {square}")
                elif tactics.VALUES[victim_type] > tactics.VALUES[piece_type]:
                    reasons.append(f"wins a {victim} for a cheaper piece")
                else:
                    reasons.append(f"captures the {victim} on {square}")

        for motif in tactics.motifs_for_move(board, move):
            reasons.append(motif.text)

        if after.is_check():
            reasons.append("gives check")

        own_hanging = set(tactics.hanging_pieces(board, board.turn))
        if own_hanging and not any(r.startswith("wins") for r in reasons):
            still_hanging = set(tactics.hanging_pieces(after, board.turn))
            if len(still_hanging) < len(own_hanging):
                saved = max(own_hanging - still_hanging, key=lambda s: tactics.VALUES[board.piece_type_at(s)])
                reasons.append(f"saves your {tactics.describe(board, saved)}")

        if board.is_castling(move):
            reasons.append("tucks your king away safely and activates your rook")
        if move.promotion:
            reasons.append(f"promotes your pawn to a {tactics.NAMES[move.promotion]}")

        if not reasons:
            reasons.extend(self._positional_reasons(board, move, piece_type))
        if not reasons:
            reasons.append("improves your position")

        reasons = reasons[:2]
        return "It " + " and ".join(reasons) + "."

    def _positional_reasons(self, board: chess.Board, move: chess.Move, piece_type: int) -> list[str]:
        color = board.turn
        home_rank = 0 if color == chess.WHITE else 7
        from_rank = chess.square_rank(move.from_square)
        to_file = chess.square_file(move.to_square)
        out = []
        in_opening = board.fullmove_number <= 12
        if piece_type in (chess.KNIGHT, chess.BISHOP) and from_rank == home_rank and in_opening:
            out.append(f"develops your {tactics.NAMES[piece_type]}")
        elif piece_type == chess.PAWN and to_file in (3, 4) and in_opening:
            out.append("fights for the center")
        elif piece_type == chess.ROOK:
            file_squares = chess.SquareSet(chess.BB_FILES[to_file])
            if not any(board.piece_type_at(s) == chess.PAWN for s in file_squares):
                out.append("puts your rook on an open file")
        elif piece_type == chess.QUEEN and in_opening and board.fullmove_number <= 4:
            out.append("brings your queen out early, so be careful of attacks on it")
        return out
