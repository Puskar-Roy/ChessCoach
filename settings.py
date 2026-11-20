"""User settings and game history, stored as small JSON files next to the program."""

import json
import os
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"  # files shipped with the program (opening book, ...)
USER_DIR = Path(os.environ.get("CHESSCOACH_DATA") or DATA_DIR)  # the user's own files (settings, history, logs)
SETTINGS_FILE = USER_DIR / "settings.json"
HISTORY_FILE = USER_DIR / "history.json"

DEFAULTS = {
    "voice": True,
    "arrows": True,
    "engine_time": 0.6,
    "appearance": "system",
    "board_theme": "Green",
    "color": "White",
    "source": "Manual",
    "monitor": 1,
    "camera": 0,
    "fen": "",
    "system": "",
    "level": "Guided",
    "strictness": "Balanced",
}


def load_settings(path: Path = SETTINGS_FILE) -> dict:
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict, path: Path = SETTINGS_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_history(path: Path = HISTORY_FILE) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add_history(entry: dict, path: Path = HISTORY_FILE) -> None:
    entry = {"ts": time.strftime("%Y-%m-%d %H:%M"), **entry}
    history = load_history(path)
    history.append(entry)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history[-200:], indent=2), encoding="utf-8")
    except OSError:
        pass
