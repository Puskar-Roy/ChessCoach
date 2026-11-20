"""Talks to the desktop app (Electron) over standard input/output, one JSON message per line.

    app -> python   {"id": 7, "cmd": "session.start", "args": {...}}
    python -> app   {"event": "state", "data": {...}}  or  {"id": 7, "ok": true, "data": {...}}

stdout carries only this protocol; anything else the program prints goes to stderr."""

import base64
import json
import queue
import sys
import threading
import traceback

import chess
import cv2

import settings as store
from controller import GameController
from game_state import GameState
from repertoire import SYSTEMS

PROTOCOL_VERSION = 1
SURE_ENOUGH = 0.6  # lowest per-piece certainty at which a mid-game position is used without asking


def describe_systems() -> list[dict]:
    return [
        {
            "id": system.id,
            "name": system.name,
            "color": "white" if system.color == chess.WHITE else "black",
            "tagline": system.tagline,
            "ideas": list(system.ideas),
            "middlegame": list(system.middlegame),
            "endgame": list(system.endgame),
            "lines": [line.name for line in system.lines],
        }
        for system in SYSTEMS.values()
    ]


class Bridge:
    def __init__(self, out):
        self._out = out
        self._write_lock = threading.Lock()
        self.settings = store.load_settings()
        self.events: queue.Queue = queue.Queue()
        self.controller = GameController(self.settings, self.events)
        self.capture = None  # ScreenCapture while a board is being selected / watched
        self.watcher = None  # prepared BoardWatcher, handed to the controller when the session starts
        self.monitor_screen = None  # last screenshot, for re-detecting

    # ------------------------------------------------------------------ output
    def send(self, message: dict) -> None:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            self._out.write(line + "\n")
            self._out.flush()

    def emit(self, event: str, data=None) -> None:
        self.send({"event": event, "data": data})

    def _pump(self) -> None:
        while True:
            kind, data = self.events.get()
            if kind == "stopped":
                self._release_capture()
            self.emit(kind, data)

    # ---------------------------------------------------------------- commands
    def handle(self, cmd: str, args: dict):
        if cmd == "hello":
            return {
                "version": PROTOCOL_VERSION,
                "settings": self.settings,
                "systems": describe_systems(),
                "history": store.load_history(),
            }
        if cmd == "settings.save":
            self.settings.update(args)
            store.save_settings(self.settings)
            return {}
        if cmd == "history.get":
            return store.load_history()
        if cmd == "history.clear":
            store.HISTORY_FILE.unlink(missing_ok=True)
            return []
        if cmd == "capture.snapshot":
            return self._snapshot(int(args.get("monitor", 1)))
        if cmd == "capture.confirm":
            return self._confirm(args)
        if cmd == "capture.inspect":
            return self._inspect(args)
        if cmd == "fen.build":
            return self._build_fen(args)
        if cmd == "capture.cancel":
            self._release_capture()
            return {}
        if cmd == "session.start":
            return self._start_session(args)
        if cmd == "session.stop":
            self.controller.stop()
            return {}
        if cmd == "session.command":  # move_uci, move_text, hint, new, undo, resign, voice, level, ...
            self.controller.send(args["kind"], **args.get("data", {}))
            return {}
        raise ValueError(f"Unknown command: {cmd}")

    # ------------------------------------------------------------ board capture
    def _release_capture(self) -> None:
        if self.watcher is not None:
            self.watcher.close()
        elif self.capture is not None:
            self.capture.release()
        self.watcher = None
        self.capture = None

    def _snapshot(self, monitor: int) -> dict:
        """Take a screenshot and look for the board on it."""
        from board_detect import detect_boards
        from screen_capture import ScreenCapture, ScreenCaptureError

        self._release_capture()
        try:
            self.capture = ScreenCapture(monitor)
        except ScreenCaptureError as error:
            raise ValueError(str(error)) from error
        screen = self.capture.read_monitor()
        self.monitor_screen = screen
        candidates = detect_boards(screen, limit=3)
        height, width = screen.shape[:2]
        scale = min(1.0, 1600 / width)
        preview = cv2.resize(screen, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else screen
        ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return {
            "image": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
            "width": width,
            "height": height,
            "monitor": {"left": self.capture.monitor_left, "top": self.capture.monitor_top},
            "candidates": [{"x": c.x, "y": c.y, "size": c.size, "confidence": c.confidence} for c in candidates],
        }

    def _confirm(self, args: dict) -> dict:
        """The user accepted a board rectangle: check it is a fresh game, learn it, and report which side is at the bottom."""
        from board_detect import detect_boards
        from screen_capture import find_board
        from watcher import BoardWatcher, StartCheck, check_start_position, to_board_image

        if self.capture is None:
            raise ValueError("Take a screenshot first.")
        x, y, size = int(args["x"]), int(args["y"]), int(args["size"])
        snapped = find_board(self.monitor_screen, (x, y, size, size)) if self.monitor_screen is not None else None
        if snapped is not None and abs(snapped[2] - size) <= 0.15 * size:
            x, y, size = snapped
        self.capture.set_region(x, y, size, size)
        fen = (args.get("fen") or "").strip() or None
        ok, frame = self.capture.read()
        if not ok:
            raise ValueError("I couldn't capture the screen.")
        image = to_board_image(frame)
        if fen:
            color = chess.WHITE if args.get("color", "white") == "white" else chess.BLACK
            check = StartCheck(True, color, "")
        else:
            check = check_start_position(image)
        if not check.ok:
            return {"ok": False, "message": check.message, "x": x, "y": y, "size": size, "joinable": "already under way" in check.message}
        board = GameState(check.user_color, fen).board
        watcher = BoardWatcher(self.capture, check.user_color)
        try:
            report = watcher.prepare(board)
        except ValueError as error:
            return {"ok": False, "message": str(error), "x": x, "y": y, "size": size}
        if report.errors > 4:
            return {"ok": False, "message": f"I could not tell {report.errors} squares apart. "
                                            "Make sure the whole board is visible and nothing covers it.",
                    "x": x, "y": y, "size": size}
        self.watcher = watcher
        region = self.capture.region
        return {
            "ok": True,
            "color": "white" if check.user_color == chess.WHITE else "black",
            "errors": report.errors,
            "region": {"x": region["left"], "y": region["top"], "size": region["width"]},
            "fen": board.fen() if fen else "",
        }

    def _inspect(self, args: dict) -> dict:
        """Read the pieces of a game in progress: who is where, grouped by look, with a guess for each group."""
        from piece_cluster import analyse_position
        from watcher import to_board_image

        if self.capture is None:
            raise ValueError("Take a screenshot first.")
        x, y, size = int(args["x"]), int(args["y"]), int(args["size"])
        self.capture.set_region(x, y, size, size)
        ok, frame = self.capture.read()
        if not ok:
            raise ValueError("I couldn't capture the screen.")
        image = to_board_image(frame)
        result = analyse_position(image)
        if not result["ok"]:
            return {"ok": False, "message": result["message"]}
        cell = image.shape[0] // 8
        groups = []
        for group in result["groups"]:
            first = group["squares"][0]
            r, c = divmod(first, 8)
            crop = cv2.resize(image[r * cell : (r + 1) * cell, c * cell : (c + 1) * cell], (84, 84), interpolation=cv2.INTER_CUBIC)
            ok, encoded = cv2.imencode(".png", crop)
            groups.append({
                "id": group["id"], "color": group["color"], "squares": group["squares"], "guess": group["guess"],
                "example": "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
            })
        from piece_cluster import read_position

        position = read_position(result)
        reading = result.get("reading") or {}
        sure = bool(position) and reading.get("sure", 0) >= SURE_ENOUGH
        bottom = {"w": 0, "b": 0}
        for group in groups:
            for square in group["squares"]:
                if square // 8 >= 5:
                    bottom[group["color"]] += 1
        return {
            "ok": True, "groups": groups, "x": x, "y": y, "size": size, "turn": result.get("turn"),
            "position": position, "confident": sure, "sure": reading.get("sure"),
            "userColor": position["userColor"] if position else ("white" if bottom["w"] >= bottom["b"] else "black"),
        }

    def _build_fen(self, args: dict) -> dict:
        from piece_cluster import build_fen

        cells = {int(k): v for k, v in args["cells"].items() if v}
        fen, message = build_fen(cells, args.get("userColor", "white") == "white", args.get("turn", "w"), args.get("castling") or "-")
        return {"ok": True, "fen": fen} if fen else {"ok": False, "message": message}

    # ----------------------------------------------------------------- session
    def _start_session(self, args: dict) -> dict:
        for key in ("voice", "arrows", "engine_time", "system", "level", "strictness"):
            if key in args:
                self.settings[key] = args[key]
        store.save_settings(self.settings)
        color = chess.WHITE if args.get("color", "white") == "white" else chess.BLACK
        source = "Screen" if args.get("source") == "screen" else "Manual"
        fen = (args.get("fen") or "").strip() or None
        if source == "Screen" and self.watcher is None:
            raise ValueError("Select the board first.")
        self.controller.start(color, source, fen, watcher=self.watcher if source == "Screen" else None)
        return {}

    # --------------------------------------------------------------------- run
    def run(self, stdin) -> None:
        threading.Thread(target=self._pump, daemon=True).start()
        inbox: queue.Queue = queue.Queue()

        def worker() -> None:  # one at a time, in order: a move must never overtake the hint typed before it
            while True:
                message = inbox.get()
                if message is None:
                    return
                self._dispatch(message)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.emit("ready", {"version": PROTOCOL_VERSION})
        for raw in stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                inbox.put(json.loads(raw))
            except ValueError:
                continue
        inbox.put(None)
        thread.join(timeout=5)
        self.controller.stop()
        self._release_capture()

    def _dispatch(self, message: dict) -> None:
        request_id = message.get("id")
        try:
            data = self.handle(message.get("cmd", ""), message.get("args") or {})
            if request_id is not None:
                self.send({"id": request_id, "ok": True, "data": data})
        except Exception as error:
            traceback.print_exc()
            if request_id is not None:
                self.send({"id": request_id, "ok": False, "error": str(error)})


def main() -> int:
    out = sys.stdout
    sys.stdout = sys.stderr  # stray prints must never corrupt the protocol
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8")
    Bridge(out).run(sys.stdin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
