"""Synchronized software mute with generations invalidating in-flight input."""

from contextlib import contextmanager
from threading import Event, RLock, Thread


class SoftwareMute:
    def __init__(self, muted=False):
        self.lock = RLock()
        self.muted = muted
        self.software_muted = muted
        self.physical_muted = False
        self.generation = 0
        self.cancel = Event()
        if muted:
            self.cancel.set()

    def snapshot(self):
        with self.lock:
            return self.generation, self.cancel

    def set_muted(self, muted):
        with self.lock:
            self.software_muted = bool(muted)
            return self._transition(self.software_muted or self.physical_muted)

    def set_physical_muted(self, muted):
        with self.lock:
            self.physical_muted = bool(muted)
            return self._transition(self.software_muted or self.physical_muted)

    def _transition(self, muted):
        with self.lock:
            if self.muted == muted:
                return False
            self.cancel.set()  # Never clear an old recording's cancellation.
            self.generation += 1
            self.muted = muted
            self.cancel = Event()
            if muted:
                self.cancel.set()
            return True

    @contextmanager
    def guard(self, generation):
        """Serialize short acceptance steps against mute transitions."""
        with self.lock:
            yield not self.muted and generation == self.generation


class WindowsMuteHotkey:
    """Poll the focused Windows console: M toggles software mute."""

    def __init__(self, toggle, keyboard=None, interrupt=None):
        if keyboard is None:
            import msvcrt
            keyboard = msvcrt
        self.keyboard = keyboard
        self.toggle = toggle
        self.interrupt = interrupt
        self.stop_event = Event()
        self.thread = None

    def start(self):
        self.thread = Thread(target=self._run, name="nova-mute-key", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.wait(0.05):
            if self.keyboard.kbhit():
                key = self.keyboard.getwch()
                if key in {"\x00", "\xe0"}:
                    self.keyboard.getwch()  # Consume the rest of a special key.
                elif key.lower() == "m":
                    self.toggle()
                elif key.lower() == "s" and self.interrupt is not None:
                    self.interrupt()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)


class PosixMuteConsole:
    """Focused Linux terminal: M + Enter toggles mute; S + Enter interrupts.

    Retains canonical terminal mode. Noninteractive stdin is rejected.
    """
    def __init__(self, toggle, interrupt=None, stream=None, ready=None, on_unavailable=None):
        import sys
        self.stream = stream if stream is not None else sys.stdin
        if not self.stream.isatty():
            raise RuntimeError("Interactive terminal required for Linux software mute controls.")
        if ready is None:
            import select
            ready = lambda stream: bool(select.select([stream], [], [], 0)[0])
        self.ready = ready
        self.toggle, self.interrupt = toggle, interrupt
        self.on_unavailable = on_unavailable
        self.stop_event = Event()
        self.thread = None

    def start(self):
        self.thread = Thread(target=self._run, name="nova-mute-console", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.wait(.05):
            try:
                if not self.ready(self.stream):
                    continue
                line = self.stream.readline()
            except (OSError, ValueError):
                line = ""
            if not line:
                if self.on_unavailable is not None:
                    self.on_unavailable()
                self.stop_event.set()
                return
            key = line.strip().lower()
            if key == "m":
                self.toggle()
            elif key == "s" and self.interrupt is not None:
                self.interrupt()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
