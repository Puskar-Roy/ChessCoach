"""Text-to-speech wrapper. Speaks on a background thread so move input never blocks.

On Windows it talks to the system speech engine (SAPI) directly. pyttsx3 is only the fallback: on
Windows its run loop returns immediately after the first sentence, so the voice went silent after a
round or two."""

import queue
import threading
import time


class _SapiBackend:
    """Windows speech engine through COM. Must be used from the thread that created it."""

    def __init__(self, rate: int):
        import comtypes
        import comtypes.client

        self._comtypes = comtypes
        comtypes.CoInitialize()
        self._voice = comtypes.client.CreateObject("SAPI.SpVoice")
        self._voice.Rate = max(-10, min(10, round((rate - 180) / 12)))

    def speak(self, text: str) -> None:
        self._voice.Speak(text, 1)  # SVSFlagsAsync

    def busy(self) -> bool:
        return not self._voice.WaitUntilDone(1)

    def purge(self) -> None:
        self._voice.Speak("", 2)  # SVSFPurgeBeforeSpeak: drops whatever is being said

    def close(self) -> None:
        self._voice = None
        self._comtypes.CoUninitialize()


class _Pyttsx3Backend:
    """Fallback for other platforms: a fresh engine for every sentence (a reused one goes quiet)."""

    def __init__(self, rate: int):
        import pyttsx3

        self._pyttsx3 = pyttsx3
        self._rate = rate
        pyttsx3.init()  # fail early if there is no speech engine

    def speak(self, text: str) -> None:
        engine = self._pyttsx3.init()
        engine.setProperty("rate", self._rate)
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    def busy(self) -> bool:
        return False  # speak() blocks until the sentence is finished

    def purge(self) -> None:
        pass

    def close(self) -> None:
        pass


def _open_backend(rate: int):
    errors = []
    for backend in (_SapiBackend, _Pyttsx3Backend):
        try:
            return backend(rate)
        except Exception as exc:  # missing module, no audio device, wrong platform...
            errors.append(f"{backend.__name__}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


class Voice:
    def __init__(self, enabled: bool = True, rate: int = 170):
        self.enabled = enabled
        self.available = False
        self.on_say = None  # optional callback(text), called for every line even when muted (for subtitles)
        self._rate = rate
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None
        if enabled:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=10)

    @property
    def error(self) -> str | None:
        return self._error

    def _worker(self) -> None:
        try:
            backend = _open_backend(self._rate)
            self.available = True
        except Exception as exc:
            self._error = str(exc)
            self._ready.set()
            return
        self._ready.set()
        waiting: list[str] = []
        finishing = False
        try:
            while True:
                text = None
                if waiting:
                    text = waiting.pop(0)
                else:
                    if finishing:
                        break
                    try:
                        command = self._queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if command is None:
                        break
                    kind, payload = command
                    if kind == "purge":
                        backend.purge()
                        continue
                    text = payload
                try:
                    backend.speak(text)
                    while backend.busy():
                        try:
                            kind, payload = self._queue.get(timeout=0.05)
                        except queue.Empty:
                            continue
                        except TypeError:  # the None that asks us to stop once the queue is spoken
                            finishing = True
                            continue
                        if kind == "purge":
                            backend.purge()
                            waiting.clear()
                            break
                        if kind == "interrupt":
                            backend.purge()
                            waiting.clear()
                            waiting.append(payload)
                            break
                        waiting.append(payload)
                except Exception as exc:
                    self._error = f"{type(exc).__name__}: {exc}"
                    time.sleep(0.2)
        finally:
            backend.close()

    def say(self, text: str, interrupt: bool = True, caption: str | None = None) -> None:
        """Queue text to be spoken. With interrupt=True the current sentence is cut off and waiting ones are dropped.

        `caption` is the written form for subtitles (defaults to the spoken text)."""
        if text and self.on_say is not None:
            self.on_say(caption or text)
        if not (self.enabled and self.available) or not text:
            return
        if interrupt:
            self.clear()
            self._queue.put(("interrupt", text))
        else:
            self._queue.put(("say", text))

    def clear(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def stop(self) -> None:
        """Stop talking right now."""
        self.clear()
        if self.available:
            self._queue.put(("purge", None))

    def mute(self) -> None:
        self.enabled = False
        self.stop()

    def unmute(self) -> None:
        self.enabled = True

    def close(self) -> None:
        """Finish speaking whatever is queued, then stop the worker."""
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=15)
