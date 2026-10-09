"""Cancellation for one owned audio subprocess, never shared inference threads."""
import subprocess
import time

from offline_ai_companion.core.cancellation import check_cancel
from offline_ai_companion.core.runtime_metrics import metrics
from functools import wraps


def tracked_child(function):
    @wraps(function)
    def run(*args, **kwargs):
        with metrics.audio_subprocess():
            return function(*args, **kwargs)
    return run


@tracked_child
def run_owned(*args, **kwargs):
    """Preserve subprocess.run timeout/kill/wait behavior in half-duplex mode."""
    return subprocess.run(*args, **kwargs)


@tracked_child
def run_cancellable(command, *, cancel_event, timeout=120, input=None):
    check_cancel(cancel_event)
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace") as child:
        first = True
        try:
            while True:
                check_cancel(cancel_event)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired("owned_audio_subprocess", timeout)
                try:
                    stdout, stderr = child.communicate(input=input if first else None,
                                                       timeout=min(.1, remaining))
                    check_cancel(cancel_event)
                    if child.returncode:
                        raise subprocess.CalledProcessError(child.returncode, "owned_audio_subprocess")
                    return subprocess.CompletedProcess("owned_audio_subprocess", child.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    first = False
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()  # This helper owns this child only.
                    child.communicate(timeout=1)
