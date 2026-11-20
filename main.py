"""Chess voice assistant: engine, opening and tactics coaching with spoken advice and subtitles.

Moves come from typing (Phase 1) and, with --camera, from the webcam (Phase 2) or, with --screen,
from a board shown on screen (chess website, screen share).
Typing always keeps working, so a bad camera read never blocks the game."""

import argparse
import sys

import chess
import chess.engine

from cli_input import HELP_TEXT, Command, CommandReader
from coach import Advice, Coach
from engine import Engine, EngineNotFound
from game_state import GameState, color_name
from openings import OpeningBook
from voice import Voice


def ask_color() -> bool:
    while True:
        try:
            answer = input("Which side are you playing? (w/b): ").strip().lower()
        except EOFError:
            sys.exit(0)
        if answer in ("w", "white"):
            return chess.WHITE
        if answer in ("b", "black"):
            return chess.BLACK
        print("Please type w or b.")


def deliver(advice: Advice, voice: Voice, session=None, show_detail: bool = True) -> None:
    if session is not None:
        session.show_move(advice.best_move)  # None (e.g. opponent's turn) removes the old arrow
    if not advice.parts:
        return
    print()
    print(advice.text)
    if show_detail and advice.detail:
        print("  Engine lines:")
        for line in advice.detail:
            print(line)
    print()
    voice.say(advice.speech, caption=advice.text)


def prompt_for(state: GameState) -> str:
    who = "Your move" if state.is_user_turn else "Opponent's move"
    return f"[{state.move_number}. {color_name(state.turn)} to play] {who} > "


def status_line(state: GameState) -> str:
    if state.is_over:
        return "Game over"
    who = "YOUR MOVE" if state.is_user_turn else "Opponent's move"
    history = state.san_history()
    last = f"  (last: {history[-1]})" if history else ""
    return f"{who}{last}"


def next_command(reader: CommandReader, session, state: GameState) -> Command:
    """Wait for typed input or, with a camera, a move seen on the board."""
    from camera_input import CameraError

    if session is None:
        return reader.get() or Command("quit")
    while True:
        typed = reader.get(timeout=0)
        if typed is not None:
            return typed
        try:
            event = session.step(state.board)
        except CameraError as error:
            print(f"\n{error} Continuing with typed moves.")
            return Command("camera_lost")
        if event is None:
            continue
        if event.kind == "quit":
            return Command("quit")
        if event.kind == "toggle_mute":
            return Command("toggle_mute")
        if event.kind == "hint":
            return Command("hint")
        if event.kind == "new_game":
            return Command("new")
        if event.kind == "moves":
            return Command("camera_moves", moves=tuple(event.moves))
        session.notify(event.message)
        print(f"\n{event.message}")
        print(prompt_for(state), end="", flush=True)


def start_camera(args: argparse.Namespace, user_color: bool, state: GameState):
    from camera_input import CameraError, CameraSession

    session = CameraSession(user_color, args.camera, args.screen)
    session.expected_note = "the starting position" if not args.fen else "the position given with --fen"
    try:
        session.open()
        what = "the board on screen" if args.screen is not None else "the pieces"
        print(f"\nSetup: have {what} in {session.expected_note}, then follow the window prompts.")
        if session.setup(state.board):
            return session
        print("Setup cancelled. Continuing with typed moves.")
    except CameraError as error:
        print(f"{error} Continuing with typed moves.")
    session.close()
    return None


def play_moves(state: GameState, moves: tuple) -> int:
    """Play camera-inferred moves. Returns how many were played."""
    played = 0
    for move in moves:
        if move not in state.board.legal_moves:
            break
        print(f"Camera saw {state.push_move(move)}.")
        played += 1
    return played


def begin_game(state: GameState, coach: Coach, voice: Voice, session) -> Advice:
    """Show the board and, if it is the user's turn, say what to play."""
    print(state.render())
    if session is not None:
        session.set_subtitle("")
    if state.is_user_turn:
        advice = coach.advise(state.board)
        deliver(advice, voice, session)
        return advice
    print("Waiting for your opponent's move.")
    return Advice()


def run(args: argparse.Namespace) -> int:
    user_color = {"white": chess.WHITE, "black": chess.BLACK}.get(args.color) if args.color else ask_color()
    voice = Voice(enabled=not args.no_voice)
    if not args.no_voice and not voice.available:
        print(f"(Voice unavailable, continuing with text only: {voice.error})")

    try:
        engine = Engine(args.engine, time_limit=args.time)
    except EngineNotFound as error:
        print(error)
        return 1

    session = None
    with engine:
        coach = Coach(engine, OpeningBook.load(), user_color)
        state = GameState(user_color, args.fen)
        if args.camera is not None or args.screen is not None:
            session = start_camera(args, user_color, state)
            if session is not None:
                session.muted = not voice.enabled
                voice.on_say = session.set_subtitle

        try:
            print(f"\nYou are playing {color_name(user_color)}. Type 'help' for commands.")
            last_advice = begin_game(state, coach, voice, session)
            reader = CommandReader()
            loop(reader, session, state, coach, voice, last_advice)
        finally:
            if session is not None:
                session.close()

    voice.close()
    return 0


def loop(reader, session, state, coach, voice, last_advice) -> None:
    while True:
        print(prompt_for(state), end="", flush=True)
        if session is not None:
            session.set_status(status_line(state))
            session.resync()
        command = next_command(reader, session, state)
        if command.kind != "move" and command.kind != "camera_moves":
            print()

        if command.kind == "quit":
            return
        if command.kind == "camera_lost":
            session.close()
            session = None  # the arrow window is closed with it
        elif command.kind == "help":
            print(HELP_TEXT)
        elif command.kind == "board":
            print(state.render())
        elif command.kind == "moves":
            print(state.history_text())
        elif command.kind in ("mute", "unmute", "toggle_mute"):
            if command.kind == "toggle_mute":
                muting = voice.enabled
            else:
                muting = command.kind == "mute"
            if muting:
                voice.mute()
            else:
                voice.unmute()
            if session is not None:
                session.muted = muting
            print("Voice muted (subtitles still show)." if muting else "Voice on.")
        elif command.kind == "repeat":
            if last_advice.parts:
                print(last_advice.text)
                voice.say(last_advice.speech, caption=last_advice.text)
            else:
                print("Nothing to repeat yet.")
        elif command.kind == "hint":
            last_advice = coach.hint(state.board)
            deliver(last_advice, voice, session)
        elif command.kind == "new":
            state.reset()
            coach.reset()
            print("New game.")
            if session is not None:
                session.resync()
            last_advice = begin_game(state, coach, voice, session)
        elif command.kind == "resign":
            print("You resigned. Good game!")
            voice.say("You resigned. Good game!")
            return
        elif command.kind == "undo":
            if state.undo() is None:
                print("No moves to undo.")
            else:
                print(state.render())
                if session is not None:
                    print("(Take the move back on the board in front of you too.)")
                if state.is_user_turn:
                    last_advice = coach.hint(state.board)
                    deliver(last_advice, voice, session)
                elif session is not None:
                    session.show_move(None)
        elif command.kind == "camera_moves":
            print()
            played = play_moves(state, command.moves)
            if played:
                if session is not None:
                    session.show_move(None)  # the old arrow is out of date while the engine thinks
                last_advice = coach.advise(state.board, new_moves=played)
                deliver(last_advice, voice, session)
                announce_result(state)
        else:
            try:
                san = state.push_text(command.text)
            except ValueError as error:
                print(error)
                continue
            print(f"Played {san}.")
            last_advice = coach.advise(state.board)
            deliver(last_advice, voice, session)
            announce_result(state)


def announce_result(state: GameState) -> None:
    if state.is_over:
        print(state.result_text())
        print("Type 'undo' to take back a move, 'new' for a new game, or 'quit' to finish.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-time chess coaching with voice and subtitles.")
    parser.add_argument("--color", choices=["white", "black"], help="the side you are playing")
    parser.add_argument("--engine", help="path to the Stockfish executable")
    parser.add_argument("--time", type=float, default=0.5, help="engine thinking time per position (seconds)")
    parser.add_argument("--no-voice", action="store_true", help="text only, no speech")
    parser.add_argument("--fen", help="start from this position instead of the standard starting position")
    parser.add_argument(
        "--camera",
        nargs="?",
        const=0,
        type=int,
        metavar="INDEX",
        help="read moves from the webcam (default camera 0)",
    )
    parser.add_argument(
        "--screen",
        nargs="?",
        const=1,
        type=int,
        metavar="MONITOR",
        help="read moves from a board shown on screen, e.g. a chess website or screen share (default monitor 1)",
    )
    args = parser.parse_args()
    if args.camera is not None and args.screen is not None:
        parser.error("use either --camera or --screen, not both")
    if args.fen:
        try:
            chess.Board(args.fen)
        except ValueError as error:
            parser.error(f"invalid --fen: {error}")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nBye.")
        return 0
    except (chess.engine.EngineTerminatedError, chess.engine.EngineError) as error:
        print(f"\nThe chess engine stopped working ({error}). Please restart the program.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
