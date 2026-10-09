"""Per-turn cooperative cancellation, isolated from background workers."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event, Lock
import time

_cancel = ContextVar("nova_response_cancel", default=None)


class ResponseInterrupted(RuntimeError):
    def __init__(self):
        super().__init__("Response interrupted; committed operations are preserved.")


def current_cancel():
    return _cancel.get()


def check_cancel(event=None):
    event = current_cancel() if event is None else event
    if event is not None and event.is_set():
        raise ResponseInterrupted()


@contextmanager
def cancellation_scope(event):
    marker = _cancel.set(event)
    try:
        check_cancel()
        yield
    finally:
        _cancel.reset(marker)


def cancellable_wait(seconds):
    event = current_cancel()
    if event is None:
        time.sleep(seconds)
    elif event.wait(seconds):
        raise ResponseInterrupted()


@dataclass
class ResponseToken:
    number: int
    cancel: Event = field(default_factory=Event)
    reference: str = ""


class ResponseControl:
    def __init__(self):
        self.lock = Lock()
        self.current = None
        self.sequence = 0

    def begin(self):
        with self.lock:
            if self.current:
                self.current.cancel.set()
            self.sequence += 1
            self.current = ResponseToken(self.sequence)
            return self.current

    def interrupt(self, expected=None):
        with self.lock:
            token = self.current
            if token is None or (expected is not None and token is not expected) or token.cancel.is_set():
                return False
            token.cancel.set()
            return True

    def finish(self, token):
        with self.lock:
            token.reference = ""
            if self.current is token:
                self.current = None

    def set_reference(self, token, text):
        with self.lock:
            if self.current is token:
                token.reference = text

    def snapshot(self, token):
        with self.lock:
            return self.current is token and not token.cancel.is_set(), token.reference
