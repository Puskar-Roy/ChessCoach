import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(autouse=True)
def mouse_is_up(monkeypatch):
    """Tests must not depend on the real mouse: the watcher pauses while a button is held."""
    import watcher

    monkeypatch.setattr(watcher, "mouse_button_down", lambda: False)
