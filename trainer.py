"""A coach that teaches an opening system instead of just naming the engine's best move.

You choose a system (say the English Opening) before the game. The coach then:
  * suggests the system's move (book line first, then the next step of the setup), and explains WHY;
  * only overrides it when the move would lose material or fall into a tactic;
  * tells you how the system answers each opponent move and what to do when they leave the lines;
  * switches to middlegame plans and endgame principles as the game moves on.

Learning levels: Guided (arrow + explanation), Practice (think first, Hint reveals), Test (no help until you ask)."""

from dataclasses import dataclass

import chess

import repertoire
from coach import Advice, Coach, san_marker
from engine import Engine
from openings import OpeningBook
from repertoire import System

LEVELS = ("Guided", "Practice", "Test")


def _short(line_name: str) -> str:
    """'Reversed Sicilian (vs 1...e5)' -> 'Reversed Sicilian'."""
    return line_name.split(" (")[0]
STRICTNESS = {"Stick to the system": 220, "Balanced": 130, "Engine first": 50}


@dataclass
class Suggestion:
    move: chess.Move | None
    parts: list[str]
    source: str  # "book" | "setup" | "plan" | "engine" | "override"


class TrainerCoach(Coach):
    def __init__(self, engine: Engine, book: OpeningBook, user_color: bool, system: System,
                 level: str = "Guided", tolerance: int = 130):
        super().__init__(engine, book, user_color)
        self.system = system
        self.level = level if level in LEVELS else "Guided"
        self.tolerance = tolerance
        self.active = True  # False when the game is not one this system is for
        self.followed: dict[int, bool] = {}
        self._said: set[str] = set()
        self._plan_turn = 0

    # ------------------------------------------------------------------- state
    def reset(self) -> None:
        super().reset()
        self.followed.clear()
        self._said.clear()
        self.active = True
        self._plan_turn = 0

    def forget_after(self, ply_count: int) -> None:
        super().forget_after(ply_count)
        for ply in [p for p in self.followed if p > ply_count]:
            del self.followed[ply]

    def system_stats(self) -> dict:
        return {"followed": sum(self.followed.values()), "total": len(self.followed)}

    def current_phase(self, board: chess.Board) -> str:
        return repertoire.phase(board, self.system.setup_complete(board))

    # ------------------------------------------------------------------ advice
    def advise(self, board: chess.Board, new_moves: int = 1) -> Advice:
        if self.active and not self.system.applies(board):
            self.active = False
            advice = super().advise(board, new_moves)
            first = chess.Board().san(board.move_stack[0])
            advice.parts.insert(0, f"White opened with {first}, so this is not a {self.system.name} game. "
                                   "I'll coach normally this time.")
            return advice
        if not self.active:
            return super().advise(board, new_moves)

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
                comment = (self._my_move_comment if replay.turn == self.user_color else self._opponent_comment)(replay, after, move)
                if comment:
                    advice.parts.append(comment)
                if len(after.move_stack) in self.grades:
                    advice.grade = self.grades[len(after.move_stack)][0]
                replay = after

        phase = self.current_phase(board)
        self._phase_sentence(board, phase, advice)
        if board.turn == self.user_color:
            threats = self._threat_sentences(board)
            advice.parts.extend(threats[:1])
            suggestion = self._suggest(board)
            if self.level == "Guided":
                advice.parts.extend(suggestion.parts)
                advice.best_move = suggestion.move
            else:
                advice.parts.append(self._prompt(board, phase, suggestion))
            advice.best_move_hidden = suggestion.move
        elif board.move_stack:
            advice.parts.append("Now wait for your opponent's reply, and I'll guide your next move.")
        self._fill_plan(board, phase, advice)
        return advice

    def hint(self, board: chess.Board) -> Advice:
        if not self.active:
            return super().hint(board)
        advice = Advice()
        if board.is_game_over(claim_draw=True):
            advice.parts.append(self._game_over_sentence(board))
        elif board.turn != self.user_color:
            advice.parts.append("It's your opponent's turn. I'll guide your move as soon as they've played.")
        else:
            suggestion = self._suggest(board)
            advice.parts.extend(suggestion.parts)
            advice.best_move = suggestion.move
        self._fill_plan(board, self.current_phase(board), advice)
        return advice

    # ---------------------------------------------------------- move feedback
    def _my_move_comment(self, before: chess.Board, after: chess.Board, move: chess.Move) -> str:
        ply = len(after.move_stack)
        san = before.san(move)
        engine_text = super()._feedback(before, after, move)  # records the engine grade
        grade = self.grades.get(ply, ("best", 0))[0]
        system = self.system
        index = system._index()["mine"].get(before.epd(), [])
        book = index[0] if index else None
        matched = next((item for item in index if item.move == move), None)
        step = system.step_for(before, move)
        self.followed[ply] = bool(matched or step)
        if matched:
            text = f"{san}. {matched.note}"
        elif step and book:
            text = (f"{san} belongs to the {system.name} setup ({step.why}) but a little early: "
                    f"in the {_short(book.line)} the usual move is {san_marker(book.san)}. {book.note}")
        elif step:
            text = f"{san} fits the {system.name} plan. {step.why}"
        elif book:
            text = (f"In the {_short(book.line)} the usual move is {san_marker(book.san)}: {book.note} "
                    f"You played {san}, which leaves the system.")
        else:
            text = f"{san} is outside the {system.name} plan."
        if grade in ("mistake", "blunder") and engine_text:
            text += " " + engine_text
        return text

    def _opponent_comment(self, before: chess.Board, after: chess.Board, move: chess.Move) -> str:
        system = self.system
        san = before.san(move)
        note = system.reply_note(before, move)
        line = system.line_for_reply(before, move)
        if note:
            text = f"Your opponent played {san}. {note}"
        elif line:
            text = f"Your opponent played {san}, as expected in the {_short(line)}."
        elif system.in_book(before) or "left" not in self._said:
            self._said.add("left")
            text = (f"Your opponent played {san}, which is outside the lines I know. "
                    "Don't worry: keep to your plan and check for tactics before each move.")
        else:
            text = f"Your opponent played {san}."
        punish = super()._feedback(before, after, move)
        return text + (" " + punish if punish else "")

    # ------------------------------------------------------------- suggestions
    def _loss(self, board: chess.Board, move: chess.Move, best_cp: int) -> tuple[int, list, chess.Board]:
        """Centipawns lost by `move` compared with the engine's best, plus the engine's reply lines."""
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            return 0, [], after
        lines = self.analyse(after)
        if not lines:
            return 0, [], after
        return max(0, best_cp - lines[0].cp(self.user_color)), lines, after

    def _suggest(self, board: chess.Board) -> Suggestion:
        system = self.system
        lines = self.analyse(board)
        best = lines[0] if lines else None
        best_cp = best.cp(self.user_color) if best else 0

        candidates: list[tuple[chess.Move, str, str, str | None]] = []
        book = system.book_move(board)
        if book:
            candidates.append((book.move, book.note, "book", book.line))
        for step, moves in system.next_setup(board)[:4]:
            candidates.append((moves[0], step.why, "setup", None))

        warnings: list[str] = []
        for move, why, source, line in candidates[:3]:
            after_board = board.copy(stack=False)
            after_board.push(move)
            if best and move == best.move:
                loss, after_lines = 0, []
            else:
                loss, after_lines, after_board = self._loss(board, move, best_cp)
            san = board.san(move)
            if loss <= self.tolerance:
                if source == "book":
                    lead = (f"In the {_short(line)}, play {san_marker(san)}." if len(board.move_stack) >= 2
                            else f"Start with {san_marker(san)}.")
                else:
                    lead = f"Continue your setup with {san_marker(san)}."
                parts = [f"{lead} {why}"]
                if loss >= 60:
                    parts.append(f"(The engine would pick {san_marker(best.san)}, but this keeps you in the system and is still sound.)")
                return Suggestion(move, parts, source)
            reason = self._consequence(after_board, after_lines[0]) if after_lines else ""
            warnings.append(f"{san_marker(san)} is the system move, but here it loses material or runs into a tactic.{reason}")

        if best is None:
            return Suggestion(None, [], "engine")
        if warnings:
            return Suggestion(best.move, [warnings[0] + f" Play {san_marker(best.san)} instead, and return to the system afterwards."], "override")

        phase = self.current_phase(board)
        plan = self._next_plan(phase)
        explain = self._explain(board, best)
        text = f"The {system.name} setup is done. {plan} A good move now is {san_marker(best.san)}. {explain}"
        return Suggestion(best.move, [text], "plan")

    def _prompt(self, board: chess.Board, phase: str, suggestion: Suggestion) -> str:
        if self.level == "Test":
            return "Your move. Press Hint only if you are stuck."
        plan = self._next_plan(phase)
        if suggestion.source in ("book", "setup"):
            return f"Your move. Think: which step of the {self.system.name} comes next? Press Hint to check."
        return f"Your move. {plan} Press Hint to see a suggestion."

    # ----------------------------------------------------------- plans & phase
    def _next_plan(self, phase: str) -> str:
        pool = {"opening": self.system.ideas, "middlegame": self.system.middlegame, "endgame": self.system.endgame}[phase]
        self._plan_turn += 1
        return "Plan: " + pool[self._plan_turn % len(pool)]

    def _phase_sentence(self, board: chess.Board, phase: str, advice: Advice) -> None:
        if phase == "middlegame" and "middlegame" not in self._said:
            self._said.add("middlegame")
            advice.parts.append("The opening is behind you: we are in the middlegame. " + self.system.middlegame[0])
        elif phase == "endgame" and "endgame" not in self._said:
            self._said.add("endgame")
            advice.parts.append("We have reached an endgame. " + repertoire.endgame_tip(board))

    def _fill_plan(self, board: chess.Board, phase: str, advice: Advice) -> None:
        system = self.system
        done = sum(1 for s in system.setup if s.is_done(board))
        advice.progress = (done, len(system.setup))
        if phase == "opening":
            advice.plan_title = f"{system.name} - opening ideas"
            advice.plan = list(system.ideas)
        elif phase == "middlegame":
            advice.plan_title = f"{system.name} - middlegame plans"
            advice.plan = list(system.middlegame)
        else:
            advice.plan_title = "Endgame principles"
            advice.plan = [repertoire.endgame_tip(board), *system.endgame]
        advice.phase = phase
