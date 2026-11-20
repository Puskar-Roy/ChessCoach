"""Runs a coaching session on a background thread and reports everything to a UI through a queue.

The UI never touches the engine or the camera: it sends commands (`send`) and reads events (`events`).

Events (kind, data):
  started   {color, source}            session is live
  state     snapshot dict              board position, move list, evaluation, statistics
  advice    dict                       coach text, best move, engine lines, move grade
  arrow     uci or None                the move to draw on the UI board
  notice    str                        short message for the user
  error     str                        something went wrong
  minimize / dock {region} / restore   window hints while the screen picker is used
  stopped                              session ended
"""

import queue
import threading
import time
import traceback

import chess

import settings as store
from coach import Advice, Coach
from repertoire import get_system
from trainer import STRICTNESS, TrainerCoach
from engine import Engine, EngineNotFound
from game_state import GameState
from openings import OpeningBook
from voice import Voice

GRADES = ("best", "good", "playable", "mistake", "blunder")


def accuracy_stats(grades: dict) -> dict:
    counts = {name: 0 for name in GRADES}
    scores = []
    for grade, loss in grades.values():
        counts[grade] += 1
        scores.append(max(0.0, 100.0 - loss / 4))
    return {
        "counts": counts,
        "moves": len(scores),
        "accuracy": round(sum(scores) / len(scores), 1) if scores else None,
    }


def legal_map(board: chess.Board) -> dict:
    """{'e2': ['e3', 'e4'], ...} for the side to move (promotions listed once per target square)."""
    out: dict[str, list[str]] = {}
    for move in board.legal_moves:
        targets = out.setdefault(chess.square_name(move.from_square), [])
        name = chess.square_name(move.to_square)
        if name not in targets:
            targets.append(name)
    return out


class GameController:
    def __init__(self, settings: dict, events: "queue.Queue"):
        self.settings = settings
        self.events = events
        self.commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, color: bool, source: str, fen: str | None = None, watcher=None) -> None:
        """`watcher` is a prepared BoardWatcher when the game is read from the screen."""
        if self.running:
            return
        self.commands = queue.Queue()
        self._thread = threading.Thread(target=self._run, args=(color, source, fen, watcher), daemon=True)
        self._thread.start()

    def send(self, kind: str, **data) -> None:
        self.commands.put((kind, data))

    def stop(self, wait: float = 6.0) -> None:
        if self.running:
            self.send("stop")
            self._thread.join(timeout=wait)

    def emit(self, kind: str, data=None) -> None:
        self.events.put((kind, data))

    # ------------------------------------------------------------------ session

    def _run(self, color: bool, source: str, fen: str | None, watcher=None) -> None:
        voice = Voice(enabled=self.settings.get("voice", True))
        try:
            engine = Engine(time_limit=float(self.settings.get("engine_time", 0.6)))
        except EngineNotFound as error:
            self.emit("error", str(error))
            voice.close()
            self.emit("stopped")
            return
        try:
            with engine:
                self._session(engine, voice, color, source, fen, watcher)
        except Exception as error:  # keep the UI alive and tell the user
            self.emit("error", f"Something went wrong: {error}")
            traceback.print_exc()
        finally:
            voice.close()
            self.emit("stopped")

    def _session(self, engine: Engine, voice: Voice, color: bool, source: str, fen: str | None, watcher=None) -> None:
        system = get_system(self.settings.get("system"))
        joined = bool(fen) and chess.Board(fen).board_fen() != chess.STARTING_BOARD_FEN  # a game already under way
        if joined and system is not None:
            system = None  # an opening plan makes no sense in the middle of a game
            self.emit("notice", "You joined a game in progress, so I'll coach normally instead of following an opening.")
        if system is not None:
            color = system.color  # an opening system is played from one side only
            coach = TrainerCoach(engine, OpeningBook.load(), color, system, self.settings.get("level", "Guided"),
                                 STRICTNESS.get(self.settings.get("strictness", "Balanced"), 130))
        else:
            coach = Coach(engine, OpeningBook.load(), color)
        state = GameState(color, fen)
        ctx = {"engine": engine, "voice": voice, "coach": coach, "state": state, "session": None, "saved": False}

        live = source == "Screen" and watcher is not None
        if live:
            ctx["session"] = watcher
        self.emit("started", {"color": color, "source": "Screen" if live else "Manual",
                              "system": system.name if system else None, "joined": joined,
                              "region": watcher.capture.region if live else None})
        try:
            self._begin(ctx)
            self._loop(ctx)
        finally:
            self._save_game(ctx)
            if ctx["session"] is not None:
                ctx["session"].close()

    def _begin(self, ctx) -> None:
        state, coach = ctx["state"], ctx["coach"]
        self._state_event(ctx, with_eval=False)
        if state.is_user_turn:
            self.emit("notice", "")
            self._deliver(ctx, coach.advise(state.board))
        else:
            self.emit("notice", "Waiting for your opponent's move.")
            self._show_move(ctx, None)
        self._state_event(ctx)

    # --------------------------------------------------------------------- loop

    def _loop(self, ctx) -> None:
        from watcher import WatchError

        while True:
            session = ctx["session"]
            try:
                command = self.commands.get(timeout=0 if session else 0.1)
            except queue.Empty:
                command = None
            if command is not None:
                if not self._handle(ctx, *command):
                    return
                continue
            if session is None:
                continue
            try:
                event = session.step(ctx["state"].board)
                self._watch(ctx, session.status())
            except WatchError as error:
                self.emit("notice", f"{error} Switched to manual play.")
                session.close()
                ctx["session"] = None
                self.emit("restore")
                continue
            if event is None:
                continue
            if event.kind == "moves":
                ctx["watch"] = None
                if event.message:
                    self.emit("notice", event.message)
                self._play_moves(ctx, event.moves)
            elif event.kind == "takeback":
                ctx["watch"] = None
                self._take_back(ctx, event.plies)
                self.emit("notice", event.message)
            elif event.kind == "resync":
                ctx["watch"] = None
                self._adopt(ctx, event.fen)
                self.emit("notice", event.message)
            elif event.kind == "unclear":
                self._watch(ctx, "unclear", force=True)
                self.emit("notice", event.message)
                self._log_unclear(ctx, event)
            elif event.kind == "lost":
                self._watch(ctx, "lost", force=True)
                self.emit("notice", event.message)
            elif event.kind == "relocked":
                ctx["watch"] = None
                self.emit("notice", event.message)
                if event.region:
                    self.emit("region", {"x": event.region[0], "y": event.region[1], "size": event.region[2]})

    def _handle(self, ctx, kind: str, data: dict) -> bool:
        state, coach, voice, session = ctx["state"], ctx["coach"], ctx["voice"], ctx["session"]
        if kind == "stop":
            return False
        if kind == "move_uci":
            try:
                move = chess.Move.from_uci(data["uci"])
            except ValueError:
                return True
            if move not in state.board.legal_moves:
                self.emit("notice", "That move is not legal.")
                self._state_event(ctx, with_eval=False)
                return True
            self._apply(ctx, [move])
        elif kind == "move_text":
            try:
                move = state.parse_move(data["text"])
            except ValueError as error:
                self.emit("notice", str(error))
                return True
            self._apply(ctx, [move])
        elif kind == "hint":
            self._deliver(ctx, coach.hint(state.board))
        elif kind == "repeat":
            advice = ctx.get("last_advice")
            if advice is not None:
                voice.say(advice.speech, caption=advice.text)
        elif kind == "new":
            self._save_game(ctx)
            state.reset()
            coach.reset()
            ctx["saved"] = False
            self.emit("notice", "New game.")
            if session is not None:
                session.resync()
            self._begin(ctx)
        elif kind == "undo":
            if state.undo() is None:
                self.emit("notice", "No moves to undo.")
            else:
                coach.forget_after(len(state.board.move_stack))
                if session is not None:
                    self.emit("notice", "Take the move back on the board in front of you too.")
                self._state_event(ctx, with_eval=False)
                if state.is_user_turn:
                    self._deliver(ctx, coach.hint(state.board))
                else:
                    self._show_move(ctx, None)
                self._state_event(ctx)
        elif kind == "resign":
            voice.say("You resigned. Good game!")
            self.emit("notice", "You resigned. Good game!")
            self._save_game(ctx, result="Resigned")
            self._show_move(ctx, None)
        elif kind == "voice":
            if data["on"]:
                voice.unmute()
            else:
                voice.mute()
        elif kind == "arrows":
            self.settings["arrows"] = data["on"]
            advice = ctx.get("last_advice")
            self._show_move(ctx, advice.best_move if advice is not None and state.is_user_turn else None)
        elif kind == "time":
            ctx["engine"].time_limit = float(data["seconds"])
        elif kind == "level":
            if isinstance(coach, TrainerCoach):
                coach.level = data["level"]
        elif kind == "strictness":
            if isinstance(coach, TrainerCoach):
                coach.tolerance = STRICTNESS.get(data["strictness"], 130)
        elif kind == "flip_turn":
            # joined a game and the side to move was guessed wrong: swap it and advise again
            state.board.turn = not state.board.turn
            state.board.ep_square = None
            if session is not None:
                session.resync()
            self._begin(ctx)
        elif kind == "reread":
            if session is not None:
                session.reread()
        return True

    def _take_back(self, ctx, plies: int) -> None:
        """The board on the screen went back by `plies` moves."""
        state, coach, session = ctx["state"], ctx["coach"], ctx["session"]
        for _ in range(plies):
            state.undo()
        coach.forget_after(len(state.board.move_stack))
        if session is not None:
            session.resync()
        self._state_event(ctx, with_eval=False)
        if state.is_user_turn:
            self._deliver(ctx, coach.hint(state.board))
        else:
            self._show_move(ctx, None)
        self._state_event(ctx)

    def _adopt(self, ctx, fen: str) -> None:
        """Carry on from the position on the screen (a new game, or more changes than could be followed)."""
        state, session = ctx["state"], ctx["session"]
        board = chess.Board(fen)
        if board.board_fen() == chess.STARTING_BOARD_FEN and board.turn == chess.WHITE:
            self._save_game(ctx)
            state.start_fen = None
            state.reset()
            ctx["coach"].reset()
            ctx["saved"] = False
        else:
            state.board = board
            state.start_fen = fen
            if isinstance(ctx["coach"], TrainerCoach):  # an opening plan no longer applies
                ctx["coach"] = Coach(ctx["engine"], OpeningBook.load(), state.user_color)
        if session is not None:
            session.resync()
        self._begin(ctx)

    def _watch(self, ctx, status: str, force: bool = False) -> None:
        """Tell the UI what the board reader is doing, only when it changes."""
        if ctx.get("watch") == "unclear" and not force and status == "watching":
            return  # keep showing 'unclear' until a move is read or the user re-reads
        if ctx.get("watch") != status:
            ctx["watch"] = status
            self.emit("watch", status)

    @staticmethod
    def _keep_picture(event) -> None:
        """Keep the board picture (only the board, only on this computer) of a reading that failed; the newest 12."""
        if getattr(event, "image", None) is None:
            return
        import cv2

        folder = store.USER_DIR / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / f"unclear-{time.strftime('%H%M%S')}.png"), event.image)
        for old in sorted(folder.glob("unclear-*.png"), key=lambda p: p.stat().st_mtime)[:-12]:
            old.unlink(missing_ok=True)

    def _log_unclear(self, ctx, event) -> None:
        """Keep a small local record of boards that could not be read, to help improve detection."""
        try:
            from board_reader import grid_to_text
            from move_inference import expected_grid

            state = ctx["state"]
            expected = expected_grid(state.board, state.user_color)
            path = store.USER_DIR / "debug.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            seen = ", ".join(event.doubtful) or "(none)"
            self._keep_picture(event)
            stamp = time.strftime("%H:%M:%S")
            with path.open("a", encoding="utf-8") as log:
                log.write("\n".join([f"--- {stamp} {event.message}", state.board.fen(), "expected:",
                                     grid_to_text(expected), "seen:", seen, ""]))
        except Exception:
            pass

    # ------------------------------------------------------------------ playing

    def _play_moves(self, ctx, moves) -> None:
        legal = []
        board = ctx["state"].board.copy(stack=False)
        for move in moves:
            if move not in board.legal_moves:
                break
            legal.append(move)
            board.push(move)
        if legal:
            self._apply(ctx, legal)

    def _apply(self, ctx, moves) -> None:
        state, coach = ctx["state"], ctx["coach"]
        if state.is_over:
            self.emit("notice", "The game is over. Press New game to play again.")
            return
        for move in moves:
            state.push_move(move)
        self._show_move(ctx, None)  # the old arrow is out of date while the engine thinks
        self._state_event(ctx, with_eval=False)
        self._deliver(ctx, coach.advise(state.board, new_moves=len(moves)))
        self._state_event(ctx)
        if state.is_over:
            self._save_game(ctx)

    def _deliver(self, ctx, advice: Advice) -> None:
        ctx["last_advice"] = advice
        if advice.parts:
            ctx["voice"].say(advice.speech, caption=advice.text)
        self._show_move(ctx, advice.best_move)
        self.emit("advice", {
            "text": advice.text,
            "best": advice.best_move.uci() if advice.best_move else None,
            "lines": advice.lines,
            "grade": advice.grade,
            "plan_title": advice.plan_title,
            "plan": advice.plan,
            "progress": advice.progress,
            "phase": advice.phase,
        })

    def _show_move(self, ctx, move) -> None:
        shown = move if self.settings.get("arrows", True) else None
        self.emit("arrow", shown.uci() if shown is not None else None)

    # ------------------------------------------------------------------- output

    def _state_event(self, ctx, with_eval: bool = True) -> None:
        state, coach = ctx["state"], ctx["coach"]
        board = state.board
        evaluation = None
        if board.is_game_over():
            outcome = board.outcome(claim_draw=True)
            decided = outcome is not None and outcome.winner is not None
            evaluation = {"cp": (1000 if outcome.winner else -1000) if decided else 0, "mate": None}
        elif with_eval:
            lines = coach.analyse(board)
            if lines:
                top = lines[0]
                evaluation = {"cp": max(-1000, min(1000, top.cp(chess.WHITE))), "mate": top.mate(chess.WHITE)}
        self.emit("state", {
            "fen": board.fen(),
            "last": board.peek().uci() if board.move_stack else None,
            "user_color": state.user_color,
            "user_turn": state.is_user_turn,
            "sans": state.san_history(),
            "over": state.is_over,
            "result": state.result_text(),
            "eval": evaluation,
            "stats": accuracy_stats(coach.grades),
            "system": coach.system_stats() if isinstance(coach, TrainerCoach) else None,
            "check": board.is_check(),
            "legal": legal_map(board),
        })

    def _save_game(self, ctx, result: str | None = None) -> None:
        if ctx.get("saved"):
            return
        state, coach = ctx["state"], ctx["coach"]
        stats = accuracy_stats(coach.grades)
        if not state.board.move_stack or not stats["moves"]:
            return
        ctx["saved"] = True
        store.add_history({
            "color": "White" if state.user_color == chess.WHITE else "Black",
            "plies": len(state.board.move_stack),
            "result": result or state.result_text() or "Unfinished",
            "accuracy": stats["accuracy"],
            "counts": stats["counts"],
            "system": coach.system.name if isinstance(coach, TrainerCoach) else None,
            "followed": coach.system_stats() if isinstance(coach, TrainerCoach) else None,
        })
