"""Privacy-safe audio diagnostics: fixed event labels, counts and device metadata."""
import logging
import os
from contextlib import contextmanager
from time import perf_counter

import sounddevice as sd
from offline_ai_companion.core.cancellation import ResponseInterrupted
from offline_ai_companion.core.runtime_metrics import metrics

logger = logging.getLogger("nova.audio")
STAGES = {"capture", "transcription", "processing", "synthesis", "playback"}


def enabled():
    return os.getenv("NOVA_AUDIO_DIAGNOSTICS", "false").lower() in {"true", "1", "yes", "on"}


@contextmanager
def stage(name):
    if name not in STAGES:
        raise ValueError("Unsupported audio diagnostic stage.")
    started = perf_counter()
    outcome = "ok"
    error_type = "none"
    try:
        yield
    except BaseException as exc:
        outcome = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit, ResponseInterrupted)) else "error"
        error_type = type(exc).__name__
        raise
    finally:
        metrics.observe("audio_" + name, perf_counter() - started, outcome)
        if enabled() or outcome != "ok":
            # Do not format exception messages, arguments, paths or audio/text.
            print(f"[AUDIO DIAG] stage={name} status={outcome} error_type={error_type} "
                  f"duration_ms={(perf_counter() - started) * 1000:.3f}", flush=True)


def event(name):
    if name not in {"stream_open", "stream_closed", "stream_close_failed", "stale_recording_discarded", "playback_guard_enter", "playback_guard_exit"}:
        raise ValueError("Unsupported audio diagnostic event.")
    if enabled():
        print(f"[AUDIO DIAG] event={name}", flush=True)


def device_inventory(include_names=False, backend=None):
    """Query PortAudio metadata only; do not open streams or load memory/models."""
    backend = sd if backend is None else backend
    try:
        devices = backend.query_devices()
        defaults = tuple(backend.default.device)
        result = []
        for index, device in enumerate(devices):
            row = {"id": index, "hostapi": int(device["hostapi"]),
                   "input_channels": int(device["max_input_channels"]),
                   "output_channels": int(device["max_output_channels"]),
                   "default_samplerate": float(device["default_samplerate"]),
                   "default_input": index == defaults[0], "default_output": index == defaults[1]}
            if include_names:
                # Names are local device labels, potentially personal; explicit opt-in.
                row["name"] = str(device["name"])
            result.append(row)
        return {"status": "ok", "devices": result}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "devices": []}


def input_format_check(device=None, backend=None):
    backend = sd if backend is None else backend
    try:
        backend.check_input_settings(device=device, channels=1, samplerate=16000, dtype="float32")
        return {"status": "ok", "sample_rate": 16000, "channels": 1}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "sample_rate": 16000, "channels": 1}


def output_format_check(device=None, backend=None):
    backend = sd if backend is None else backend
    try:
        backend.check_output_settings(device=device, channels=1, samplerate=22050, dtype="float32")
        return {"status": "ok", "sample_rate": 22050, "channels": 1}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "sample_rate": 22050, "channels": 1}
