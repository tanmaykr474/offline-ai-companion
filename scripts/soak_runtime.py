"""Synthetic soak: real voice orchestration/SQLite, no hardware or model service."""
import argparse
from collections import deque
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import importlib.util
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread, Timer, active_count
import time
from unittest.mock import patch

import httpx
import numpy as np
import soundfile as sf

from offline_ai_companion.audio.continuous_recorder import ContinuousRecorder
from offline_ai_companion.audio.recovery import AudioRecovery
from offline_ai_companion.audio.temporary import TemporaryAudio
from offline_ai_companion.core.activation_controller import ActivationController
from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.cancellation import check_cancel
from offline_ai_companion.core.performance import timed
from offline_ai_companion.core.runtime_metrics import metrics, RuntimeMonitor
from offline_ai_companion.core.state import AssistantState
from offline_ai_companion.llm.ollama import OllamaLLM
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.passive_worker import PassiveMemoryWorker
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.scheduler.reminder_notifications import ReminderNotifications
from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
from offline_ai_companion.tools.memory_tools import MemoryTools


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError("Synthetic soak synchronization timed out.")
        Event().wait(.005)


class SyntheticInput:
    open_count = 0
    close_count = 0
    silence = False

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.blocksize = kwargs["blocksize"]
        self.stop = Event()

    def __enter__(self):
        type(self).open_count += 1
        def feed():
            index = 0
            while not self.stop.is_set():
                amplitude = .1 if index < 3 and not self.silence else 0.
                self.callback(np.full((self.blocksize, 1), amplitude, dtype=np.float32),
                              self.blocksize, None, None)
                index += 1
                self.stop.wait(.005)
        self.thread = Thread(target=feed, name="soak-input", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(2)
        if self.thread.is_alive():
            raise RuntimeError("Synthetic input did not close.")
        type(self).close_count += 1


class SyntheticSTT:
    text = ""

    @timed("transcription")
    def transcribe(self, path, cancel_event=None):
        check_cancel(cancel_event)
        return self.text


class SyntheticTTS:
    @timed("tts_generation")
    def synthesize(self, text, path, cancel_event=None):
        check_cancel(cancel_event)
        sf.write(path, np.zeros(160, dtype=np.float32), 16000)
        return path


class SyntheticPlayer:
    def __init__(self, app):
        self.app = app
        self.interrupt_next = False
        self.completed = 0

    def play(self, path, cancel_event=None):
        if self.interrupt_next:
            self.interrupt_next = False
            self.app.request_interruption()
        check_cancel(cancel_event)
        self.completed += 1


class NoExtractor:
    def extract(self, text):
        return None


class FaultProcessor(PassiveMemoryProcessor):
    fail_next = True

    def process(self, text, captured_at=None):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Synthetic extraction failure.")
        return super().process(text, captured_at=captured_at)


class ScriptedRecorder:
    def __init__(self, app, repository, model_fault):
        self.app, self.repository, self.model_fault = app, repository, model_fault
        self.real = ContinuousRecorder(block_duration=.01, silence_duration=.01,
                                       min_speech_duration=.02, preroll_duration=.01,
                                       input_stall_timeout=.5)
        self.steps = iter([
            "silence", "I enjoy listening to music.", "I love playing cricket.",
            "Nova", "What sport do I love playing?", "Nova, add a task to finish my project",
            "Nova, show my pending tasks", "Nova, remind me to take a break in 1 minute",
            "interrupt", "mute", "device_failure", "model_failure", "model_recovery",
            "due_reminder",
        ])

    @property
    def queue_depth(self):
        return self.real.queue_depth

    def record_utterance(self, path, stop_event, **kwargs):
        try:
            text = next(self.steps)
        except StopIteration:
            raise KeyboardInterrupt
        app = self.app
        self.real.privacy = app.privacy
        self.real.playback_cancel = self.playback_cancel
        if text == "device_failure":
            raise OSError("Synthetic device disconnect.")
        if text == "mute":
            app.set_muted(True)
            app.handle_transcript("Nova, add a task to muted input")
            app.set_muted(False)
            return None
        if text == "due_reminder":
            self.repository.add_reminder("synthetic due reminder", datetime.now(timezone.utc))
            wait_for(lambda: app.notifications.interrupt.is_set())
            return None
        if text == "interrupt":
            app.player.interrupt_next = True
            text = "Nova, show my pending tasks"
        if text in {"model_failure", "model_recovery"}:
            self.model_fault[0] = text == "model_failure"
            text = "Nova, tell me a short story"
        if text == "What sport do I love playing?":
            wait_for(lambda: app.passive_worker.queue.unfinished_tasks == 0)
        if text == "silence":
            SyntheticInput.silence = True
            stop = Event()
            timer = Timer(.03, stop.set)
            timer.start()
            try:
                assert self.real.record_utterance(path, stop) is None
            finally:
                timer.cancel()
                timer.join()
                SyntheticInput.silence = False
            return None
        app.stt.text = text
        return self.real.record_utterance(path, stop_event, **kwargs)


def load_app():
    path = Path(__file__).with_name("always_on_assistant.py")
    spec = importlib.util.spec_from_file_location("nova_soak_voice", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AlwaysOnAssistant


def run_soak(cycles=20, duration_seconds=None):
    if cycles is not None and cycles < 1:
        raise ValueError("Cycles must be positive.")
    if duration_seconds is not None and (not np.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError("Duration must be positive and finite.")
    if cycles is None and duration_seconds is None:
        raise ValueError("A cycle count or duration is required.")
    App = load_app()
    samples = deque(maxlen=120)
    monitor = RuntimeMonitor(sink=samples.append)
    previous_enabled = metrics.enabled
    metrics.enabled = True
    baseline = metrics.snapshot()
    started = time.monotonic()
    started_cpu = time.process_time()
    original_disable = logging.root.manager.disable
    thread_baseline = active_count()
    opened_before, closed_before = SyntheticInput.open_count, SyntheticInput.close_count
    completed = 0
    first = monitor.sample()
    samples.append(first)
    peak_rss = first["rss_bytes"] or 0
    warm_rss = None
    try:
        with TemporaryDirectory(prefix="nova-soak-") as directory, open(os.devnull, "w") as quiet:
            database = Database(Path(directory) / "soak.db")
            repository = MemoryRepository(database)
            repository.set_fact("user.favorite_language", "Python")
            logging.disable(logging.CRITICAL)
            with redirect_stdout(quiet), redirect_stderr(quiet), patch(
                    "offline_ai_companion.audio.continuous_recorder.sd.InputStream", SyntheticInput):
                while ((cycles is None or completed < cycles)
                       and (completed == 0 or duration_seconds is None or time.monotonic() - started < duration_seconds)):
                    app = App.__new__(App)
                    app.stop_event = Event()
                    app.state = AssistantState.IDLE
                    app.experimental_interruption, app.spoken_interruption = True, False
                    app.activation_controller = ActivationController()
                    fault = [False]
                    def model(request):
                        if fault[0]:
                            fault[0] = False
                            raise httpx.ReadTimeout("Synthetic timeout.", request=request)
                        return httpx.Response(200, json={"response": "A synthetic response."})
                    with httpx.Client(transport=httpx.MockTransport(model), trust_env=False) as client:
                        llm = OllamaLLM(client=client, max_retries=0)
                        app.assistant = Assistant(memory_tools=MemoryTools(repository), llm=llm,
                                                  fact_extractor=NoExtractor())
                        processor = FaultProcessor(app.assistant.passive_memory_repository, llm)
                        app.passive_worker = PassiveMemoryWorker(processor, max_queue_size=4)
                        app.notifications = ReminderNotifications(max_pending=4)
                        app.scheduler = ReminderScheduler(repository, app.notifications.request, interval_seconds=.01)
                        app.audio_recovery = AudioRecovery(retry_delay=.01)
                        app.stt, app.tts, app.player = SyntheticSTT(), SyntheticTTS(), SyntheticPlayer(app)
                        app.recorder = ScriptedRecorder(app, repository, fault)
                        owner = app._temporary_audio = TemporaryAudio(directory)
                        app.input_path, app.output_path, app.reminder_output_path = [
                            owner.path(name) for name in ("input.wav", "response.wav", "reminder.wav")]
                        monitor.health = app.runtime_health
                        app.run()
                        assert not app.scheduler.is_running and not app.passive_worker.thread.is_alive()
                        assert app.passive_worker.queue.unfinished_tasks == 0
                        assert app.notifications.pending.unfinished_tasks == 0
                        assert not owner.root.exists()
                        assert app.response_control.current is None
                        assert len(repository.list_tasks()) == 1  # muted input never writes
                        assert len(app.assistant.passive_memory_repository.list_memories()) == 1
                        assert "cricket" in app.assistant.process("What sport do I love playing?").lower()
                        reminders = repository.list_reminders()
                        assert len(reminders) == 2 and sum(item.is_completed for item in reminders) == 1
                        for task in repository.list_tasks():
                            repository.delete_task(task.id)
                        for reminder in reminders:
                            repository.delete_reminder(reminder.id)
                    # Reopen independently and check durable facts/integrity after each shutdown.
                    restarted = MemoryRepository(Database(database.path))
                    assert restarted.get_fact("user.favorite_language") == "Python"
                    with database.connect() as connection:
                        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    completed += 1
                    sample = monitor.sample()
                    samples.append(sample)
                    peak_rss = max(peak_rss, sample["rss_bytes"] or 0)
                    if warm_rss is None:
                        warm_rss = sample["rss_bytes"]
        assert active_count() == thread_baseline
        assert SyntheticInput.open_count - opened_before == SyntheticInput.close_count - closed_before
        assert metrics.snapshot()["owned_audio_subprocesses"] == baseline["owned_audio_subprocesses"]
        final = monitor.sample()
        peak_rss = max(peak_rss, final["rss_bytes"] or 0)
        aggregate = final["timings"]
        return {"scope": "synthetic_audio_models_real_orchestration_workers_sqlite",
                "physical_devices_verified": False, "cycles_completed": completed,
                "elapsed_seconds": time.monotonic() - started,
                "rss_initial_bytes": first["rss_bytes"], "rss_final_bytes": final["rss_bytes"],
                "rss_after_first_cycle_bytes": warm_rss,
                "cpu_percent_mean": (time.process_time() - started_cpu) / max(time.monotonic() - started, 1e-9) * 100,
                "rss_sampled_peak_bytes": peak_rss, "python_threads_before": thread_baseline,
                "python_threads_after": active_count(), "retained_samples": len(samples),
                "stream_opens": SyntheticInput.open_count - opened_before,
                "stream_closes": SyntheticInput.close_count - closed_before,
                "timings": aggregate, "counters": {key: value - baseline["counters"].get(key, 0)
                    for key, value in final["counters"].items()},
                "owned_audio_subprocesses_after": final["owned_audio_subprocesses"],
                "recent_samples": list(samples), "invariants_passed": True}
    finally:
        metrics.enabled = previous_enabled
        logging.disable(original_disable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--report", type=Path, default=Path("soak-report.json"))
    args = parser.parse_args()
    cycles = args.cycles if args.cycles is not None or args.duration_seconds else 20
    try:
        report = run_soak(cycles, args.duration_seconds)
    except Exception as exc:
        print("Soak failed: " + type(exc).__name__)
        return 1
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Soak passed: {report['cycles_completed']} cycles; sanitized report written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
