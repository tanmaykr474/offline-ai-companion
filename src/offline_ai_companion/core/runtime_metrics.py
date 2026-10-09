"""Opt-in, constant-space operational metrics. Never accept text payloads."""
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps, lru_cache
import json
import logging
import math
import os
from pathlib import Path
from threading import Event, Lock, Thread, active_count, current_thread
import time

COUNTERS = frozenset({
    "sqlite_failures", "sqlite_busy_failures", "audio_recovery_attempts",
    "audio_dropped_blocks", "audio_input_overflows", "audio_stalls",
    "passive_rejected_full", "passive_rejected_size", "passive_failures",
    "passive_completed", "reminder_delivery_failures", "scheduler_failures",
    "reminder_completed", "notification_rejected", "resource_sample_failures",
})
TIMINGS = frozenset({
    "transcription", "tts_generation", "ollama_response", "passive_extraction",
    "memory_retrieval", "voice_dispatch", "voice_response", "audio_capture",
    "audio_transcription", "audio_processing", "audio_synthesis", "audio_playback",
    "reminder_delivery", "reminder_lateness",
})
HEALTH = frozenset({"audio_queue_depth", "stop_audio_queue_depth", "passive_queue_depth",
                    "passive_busy_seconds", "passive_worker_alive", "scheduler_alive",
                    "notification_queue_depth"})


class Metrics:
    def __init__(self):
        self.enabled = False
        self.lock = Lock()
        self.counts = defaultdict(int)
        self.timings = {}
        self.audio_children = 0

    def count(self, name, value=1):
        if not self.enabled:
            return
        if name not in COUNTERS or not isinstance(value, int) or value < 0:
            raise ValueError("Unsupported numeric metric.")
        with self.lock:
            self.counts[name] += value

    def observe(self, name, seconds, status="ok"):
        if not self.enabled:
            return
        if name not in TIMINGS or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Unsupported numeric timing.")
        with self.lock:
            entry = self.timings.setdefault(name, {"count": 0, "errors": 0, "total_ms": 0., "max_ms": 0.})
            entry["count"] += 1
            entry["errors"] += int(status != "ok")
            entry["total_ms"] += seconds * 1000
            entry["max_ms"] = max(entry["max_ms"], seconds * 1000)

    @contextmanager
    def audio_subprocess(self):
        tracked = self.enabled
        if tracked:
            with self.lock:
                self.audio_children += 1
        try:
            yield
        finally:
            if tracked:
                with self.lock:
                    self.audio_children -= 1

    def snapshot(self):
        with self.lock:
            return {"counters": dict(self.counts),
                    "timings": {key: dict(value) for key, value in self.timings.items()},
                    "owned_audio_subprocesses": self.audio_children}


metrics = Metrics()


@lru_cache(maxsize=1)
def _windows_memory_api():
    import ctypes
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged",
                "nonpaged", "pagefile", "peak_pagefile")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    return Memory, kernel.GetCurrentProcess, psapi.GetProcessMemoryInfo


def resident_bytes():
    """Current process RSS; no process enumeration or command-line collection."""
    if os.name == "nt":
        import ctypes
        Memory, current_process, get_memory = _windows_memory_api()
        value = Memory()
        value.cb = ctypes.sizeof(value)
        if not get_memory(current_process(), ctypes.byref(value), value.cb):
            raise OSError("Process resource sample unavailable.")
        return int(value.rss)
    if Path("/proc/self/statm").exists():
        return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    return None


class ResourceSampler:
    def __init__(self):
        self.previous = (time.monotonic(), time.process_time())

    def sample(self):
        now, cpu = time.monotonic(), time.process_time()
        before, before_cpu = self.previous
        self.previous = now, cpu
        return {"rss_bytes": resident_bytes(), "python_threads": active_count(),
                "cpu_percent": max(0., (cpu - before_cpu) / max(now - before, 1e-9) * 100)}


class RuntimeMonitor:
    def __init__(self, health=lambda: {}, interval=30., sink=None, sampler=None):
        if not math.isfinite(interval) or not .1 <= interval <= 3600:
            raise ValueError("Runtime sample interval must be between 0.1 and 3600 seconds.")
        self.health, self.interval = health, interval
        self.sampler = sampler or ResourceSampler()
        self.sink = sink or self._log
        self.stop_event = Event()
        self.thread = None
        self.lifecycle_lock = Lock()

    @staticmethod
    def _log(sample):
        logging.getLogger("nova.runtime").info(json.dumps(sample, sort_keys=True))

    def sample(self):
        sample = metrics.snapshot()
        try:
            resources = self.sampler.sample()
            sample.update({key: value if isinstance(value, (int, float))
                           and math.isfinite(value) and value >= 0 else None
                           for key in ("rss_bytes", "python_threads", "cpu_percent")
                           for value in (resources.get(key),)})
        except Exception:
            metrics.count("resource_sample_failures")
            sample.update(rss_bytes=None, python_threads=active_count(), cpu_percent=None)
        try:
            health = self.health()
            sample["health"] = {key: value for key, value in health.items()
                                if key in HEALTH and isinstance(value, (int, float))
                                and math.isfinite(value) and value >= 0}
        except Exception:
            metrics.count("resource_sample_failures")
            sample["health"] = {}
        return sample

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.sink(self.sample())
            except Exception:
                metrics.count("resource_sample_failures")
            self.stop_event.wait(self.interval)

    def start(self):
        with self.lifecycle_lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = Thread(target=self._run, name="nova-runtime-monitor", daemon=True)
            try:
                self.thread.start()
            except RuntimeError:
                self.thread = None
                raise

    def stop(self):
        with self.lifecycle_lock:
            self.stop_event.set()
            thread = self.thread
        if thread is current_thread():
            return False
        if thread is not None:
            thread.join(timeout=2)
        return thread is None or not thread.is_alive()


def observed_runtime(function):
    """Opt-in lifecycle wrapper; monitoring ends even if application cleanup fails."""
    @wraps(function)
    def run(app, *args, **kwargs):
        from offline_ai_companion.config import NOVA_RUNTIME_DIAGNOSTICS, NOVA_RUNTIME_INTERVAL
        if not NOVA_RUNTIME_DIAGNOSTICS:
            return function(app, *args, **kwargs)
        logger = logging.getLogger("nova.runtime")
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)
        logger.propagate = False
        previous = metrics.enabled
        metrics.enabled = True
        monitor = RuntimeMonitor(app.runtime_health, interval=NOVA_RUNTIME_INTERVAL)
        try:
            try:
                monitor.start()
            except RuntimeError:
                metrics.count("resource_sample_failures")
            return function(app, *args, **kwargs)
        finally:
            try:
                if not monitor.stop():
                    logger.warning("Runtime monitor shutdown pending.")
            finally:
                metrics.enabled = previous
    return run
