"""Serialize capture and playback; cancellation is latched for every capture."""
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Lock, RLock


@dataclass(frozen=True)
class CaptureTicket:
    generation: int
    cancel: Event


class HalfDuplexAudio:
    def __init__(self):
        self.lock = RLock()
        self.media_lock = Lock()
        self.generation = 0
        self.cancel = Event()
        self.playback_pending = 0

    def valid(self, generation):
        with self.lock:
            return generation == self.generation and not self.playback_pending

    @contextmanager
    def capture(self, stop_event):
        acquired = False
        ticket = None
        try:
            while not stop_event.is_set():
                if self.media_lock.acquire(timeout=0.05):
                    acquired = True
                    break
            if acquired and not stop_event.is_set():
                with self.lock:
                    if not self.playback_pending:
                        ticket = CaptureTicket(self.generation, self.cancel)
            yield ticket
        finally:
            if acquired:
                self.media_lock.release()

    @contextmanager
    def playback(self):
        # Signal active capture before waiting for its stream to close.
        with self.lock:
            self.playback_pending += 1
            self.cancel.set()
            self.generation += 1
        try:
            with self.media_lock:
                yield
        finally:
            with self.lock:
                self.playback_pending -= 1
                if not self.playback_pending:
                    self.cancel = Event()
