import time

import voice as voice_module
from voice import Voice


class FakeBackend:
    """Pretends each sentence takes 0.3 s to say."""

    log: list = []

    def __init__(self, rate):
        self._until = 0.0

    def speak(self, text):
        FakeBackend.log.append(("speak", text))
        self._until = time.monotonic() + 0.3

    def busy(self):
        return time.monotonic() < self._until

    def purge(self):
        FakeBackend.log.append(("purge",))
        self._until = 0.0

    def close(self):
        pass


def make_voice(monkeypatch):
    FakeBackend.log = []
    monkeypatch.setattr(voice_module, "_open_backend", lambda rate: FakeBackend(rate))
    return Voice()


def spoken():
    return [entry[1] for entry in FakeBackend.log if entry[0] == "speak"]


def test_every_sentence_is_spoken_not_just_the_first(monkeypatch):
    voice = make_voice(monkeypatch)
    for i in range(6):
        voice.say(f"sentence {i}", interrupt=False)
    voice.close()
    assert spoken() == [f"sentence {i}" for i in range(6)]


def test_a_new_sentence_interrupts_the_current_one(monkeypatch):
    voice = make_voice(monkeypatch)
    voice.say("long first advice")
    time.sleep(0.1)
    voice.say("fresh advice")
    voice.close()
    assert spoken() == ["long first advice", "fresh advice"]
    assert ("purge",) in FakeBackend.log


def test_mute_stops_speech_and_unmute_restores_it(monkeypatch):
    voice = make_voice(monkeypatch)
    voice.say("talking")
    time.sleep(0.1)
    voice.mute()
    voice.say("ignored while muted")
    time.sleep(0.2)
    voice.unmute()
    voice.say("back again")
    voice.close()
    assert spoken() == ["talking", "back again"]


def test_voice_keeps_working_after_many_rounds(monkeypatch):
    voice = make_voice(monkeypatch)
    for round_number in range(8):
        voice.say(f"round {round_number}")
        time.sleep(0.4)
    voice.close()
    assert len(spoken()) == 8


def test_subtitles_get_text_even_when_muted(monkeypatch):
    voice = make_voice(monkeypatch)
    captions = []
    voice.on_say = captions.append
    voice.mute()
    voice.say("spoken form", caption="Written form")
    voice.close()
    assert captions == ["Written form"] and spoken() == []
