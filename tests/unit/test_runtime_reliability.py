from contextlib import contextmanager
import json
import math
import sqlite3
import subprocess
import sys
from threading import Event, Thread
from threading import Timer
from types import SimpleNamespace
import time
from unittest.mock import Mock

import numpy as np
import pytest

from offline_ai_companion.core.runtime_metrics import Metrics, RuntimeMonitor, ResourceSampler, metrics
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_worker import PassiveMemoryWorker
from offline_ai_companion.scheduler.reminder_notifications import ReminderNotifications
from offline_ai_companion.audio.continuous_recorder import ContinuousRecorder
from offline_ai_companion.audio.cancellable_subprocess import run_owned, run_cancellable


@pytest.fixture
def measured():
    previous = metrics.enabled
    metrics.enabled = True
    with metrics.lock:
        metrics.counts.clear()
        metrics.timings.clear()
    yield metrics
    assert metrics.snapshot()["owned_audio_subprocesses"] == 0
    metrics.enabled = previous


def test_disabled_metrics_collect_nothing_and_enabled_storage_is_constant_size():
    value = Metrics()
    value.count("private text")
    value.observe("private text", 1)
    assert value.snapshot()["counters"] == {} and value.snapshot()["timings"] == {}
    value.enabled = True
    for _ in range(10000):
        value.count("sqlite_failures")
        value.observe("transcription", .01)
    assert len(value.timings) == 1 and len(value.counts) == 1
    assert value.snapshot()["timings"]["transcription"]["count"] == 10000


@pytest.mark.parametrize("name", ["private transcript", "password=secret", "SELECT * FROM facts"])
def test_metric_names_cannot_include_private_payloads(name):
    value = Metrics()
    value.enabled = True
    with pytest.raises(ValueError):
        value.count(name)
    with pytest.raises(ValueError):
        value.observe(name, 1)
    assert name not in json.dumps(value.snapshot())


def test_monitor_filters_health_payloads_and_survives_sample_failures(measured):
    sampler = Mock()
    sampler.sample.side_effect = OSError("private details")
    monitor = RuntimeMonitor(lambda: {"audio_queue_depth": 2, "private": "speech",
        "passive_queue_depth": "secret", "passive_busy_seconds": math.inf}, sampler=sampler)
    result = monitor.sample()
    assert result["health"] == {"audio_queue_depth": 2}
    assert result["rss_bytes"] is None
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)
    assert measured.snapshot()["counters"]["resource_sample_failures"] == 1


def test_monitor_repeated_start_stop_releases_thread(measured):
    received = Event()
    monitor = RuntimeMonitor(interval=.1, sink=lambda sample: received.set())
    for _ in range(3):
        received.clear()
        monitor.start()
        thread = monitor.thread
        monitor.start()
        assert monitor.thread is thread
        assert received.wait(2)
        assert monitor.stop() and not thread.is_alive()


def test_native_resources_have_numeric_values_only():
    result = ResourceSampler().sample()
    assert result["rss_bytes"] is None or result["rss_bytes"] > 0
    assert result["python_threads"] >= 1 and result["cpu_percent"] >= 0


@pytest.mark.parametrize("timeout", [-1, 61, math.inf, math.nan])
def test_invalid_sqlite_busy_timeout(timeout, tmp_path):
    with pytest.raises(ValueError):
        Database(tmp_path / "db", busy_timeout_seconds=timeout)


def test_sqlite_setup_failure_always_closes_connection(tmp_path, monkeypatch, measured):
    connection = Mock()
    connection.execute.side_effect = sqlite3.OperationalError("private SQL")
    monkeypatch.setattr(sqlite3, "connect", Mock(return_value=connection))
    with pytest.raises(sqlite3.OperationalError):
        with Database(tmp_path / "db").connect():
            pytest.fail("Setup should not yield")
    connection.close.assert_called_once()
    assert measured.snapshot()["counters"]["sqlite_failures"] == 1


def test_sqlite_keyboard_interrupt_rolls_back_and_reopens(tmp_path):
    database = Database(tmp_path / "db")
    repository = MemoryRepository(database)
    repository.set_fact("user.favorite_language", "Python")
    with pytest.raises(KeyboardInterrupt):
        with database.connect() as connection:
            connection.execute("UPDATE facts SET value = 'Java'")
            raise KeyboardInterrupt
    assert repository.get_fact("user.favorite_language") == "Python"
    repository.add_task("After interruption")
    assert len(repository.list_tasks()) == 1


def test_sqlite_busy_wait_is_bounded_and_later_write_recovers(tmp_path, measured):
    database = Database(tmp_path / "db", busy_timeout_seconds=.03)
    repository = MemoryRepository(database)
    with database.connect() as lock:
        lock.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError):
            repository.add_task("Not committed")
        assert time.monotonic() - started < 2
    assert repository.list_tasks() == []
    repository.add_task("Committed after release")
    assert len(repository.list_tasks()) == 1
    assert measured.snapshot()["counters"]["sqlite_busy_failures"] == 1


def test_passive_backpressure_bounds_size_and_drains_accepted_items(measured):
    entered, release = Event(), Event()
    calls = []
    def process(text):
        entered.set()
        assert release.wait(3)
        calls.append(text)
        return 0
    worker = PassiveMemoryWorker(Mock(process=process), max_queue_size=1, max_transcript_chars=50)
    worker.start()
    try:
        assert worker.submit("I love playing cricket.")
        assert entered.wait(2)
        assert worker.busy_since is not None
        assert worker.submit("I enjoy listening to music.")
        assert not worker.submit("I work as a developer.")
        assert not worker.submit("x" * 51)
        assert not worker.stop(timeout=0)
    finally:
        release.set()
        assert worker.stop(timeout=3)
    assert len(calls) == 2 and worker.queue.unfinished_tasks == 0 and worker.busy_since is None
    assert measured.snapshot()["counters"]["passive_rejected_full"] == 1
    assert measured.snapshot()["counters"]["passive_rejected_size"] == 1


def test_worker_failure_does_not_replay_commit_or_lose_following_work(tmp_path, measured):
    repository = MemoryRepository(Database(tmp_path / "db"))
    calls = []
    def process(text):
        repository.add_note(text)
        calls.append(text)
        if len(calls) == 1:
            raise RuntimeError("Failure after commit")
        return 1
    worker = PassiveMemoryWorker(Mock(process=process))
    worker.start()
    assert worker.submit("First synthetic note")
    assert worker.submit("Second synthetic note")
    assert worker.stop(timeout=3)
    assert len(repository.list_notes()) == 2 and len(calls) == 2
    assert measured.snapshot()["counters"]["passive_failures"] == 1
    assert measured.snapshot()["counters"]["passive_completed"] == 1


def test_notification_capacity_includes_active_deliveries_and_close_releases_waiters(measured):
    notifications = ReminderNotifications(max_pending=1)
    errors = []
    def request():
        try:
            notifications.request(Mock())
        except RuntimeError as exc:
            errors.append(type(exc))
    thread = Thread(target=request)
    thread.start()
    assert notifications.interrupt.wait(2)
    active = notifications.get_pending()
    with pytest.raises(RuntimeError, match="capacity"):
        notifications.request(Mock())
    notifications.close()
    notifications.acknowledge(active)
    thread.join(2)
    assert not thread.is_alive() and errors == [RuntimeError]
    assert notifications.pending.unfinished_tasks == 0
    assert measured.snapshot()["counters"]["notification_rejected"] == 1


def test_missing_audio_blocks_close_stream_and_raise_recoverable_error(tmp_path, monkeypatch, measured):
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", lambda **kwargs: stream)
    recorder = ContinuousRecorder(input_stall_timeout=.01)
    with pytest.raises(RuntimeError, match="stopped delivering"):
        recorder.record_utterance(tmp_path / "output.wav")
    stream.__exit__.assert_called_once()
    assert recorder.queue_depth == 0 and not (tmp_path / "output.wav").exists()
    assert measured.snapshot()["counters"]["audio_stalls"] == 1


@pytest.mark.parametrize("cancellable", [True, False])
def test_real_child_timeout_reaps_owned_subprocess(monkeypatch, measured, cancellable):
    children = []
    original = subprocess.Popen
    def launch(*args, **kwargs):
        assert measured.snapshot()["owned_audio_subprocesses"] == 1
        process = original(*args, **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", launch)
    command = [sys.executable, "-c", "import time; time.sleep(20)"]
    with pytest.raises(subprocess.TimeoutExpired):
        if cancellable:
            run_cancellable(command, cancel_event=Event(), timeout=.05)
        else:
            run_owned(command, timeout=.05, capture_output=True)
    assert len(children) == 1 and children[0].poll() is not None
    assert measured.snapshot()["owned_audio_subprocesses"] == 0


@pytest.mark.parametrize("capacity", [0, -1, math.inf, math.nan, 1.5])
def test_queue_limits_must_be_positive_integers(capacity):
    with pytest.raises(ValueError):
        ReminderNotifications(max_pending=capacity)
    with pytest.raises(ValueError):
        PassiveMemoryWorker(Mock(), max_queue_size=capacity)
    with pytest.raises(ValueError):
        PassiveMemoryWorker(Mock(), max_transcript_chars=capacity)
    with pytest.raises(ValueError):
        ContinuousRecorder(queue_size=capacity)


def test_silence_keeps_delivering_blocks_and_is_not_a_stalled_device(tmp_path, monkeypatch):
    stopped = Event()
    closed = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.done = Event()
        def __enter__(self):
            def feed():
                while not self.done.is_set():
                    self.callback(np.zeros((1600, 1), dtype=np.float32), 1600, None, None)
                    self.done.wait(.005)
            self.thread = Thread(target=feed)
            self.thread.start()
            return self
        def __exit__(self, *args):
            self.done.set()
            self.thread.join(2)
            closed.append(not self.thread.is_alive())
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Stream)
    timer = Timer(.3, stopped.set)
    timer.start()
    try:
        assert ContinuousRecorder(input_stall_timeout=.01).record_utterance(tmp_path / "silence.wav", stopped) is None
    finally:
        timer.cancel()
        timer.join()
    assert closed == [True] and not (tmp_path / "silence.wav").exists()


def test_runtime_diagnostics_are_opt_in_and_stop_on_application_error(monkeypatch):
    from offline_ai_companion.core.runtime_metrics import observed_runtime
    import offline_ai_companion.config as config
    health = Mock(return_value={})
    app = SimpleNamespace(runtime_health=health)
    @observed_runtime
    def application(app):
        raise KeyboardInterrupt
    previous = metrics.enabled
    monkeypatch.setattr(config, "NOVA_RUNTIME_DIAGNOSTICS", False)
    with pytest.raises(KeyboardInterrupt):
        application(app)
    health.assert_not_called()
    monkeypatch.setattr(config, "NOVA_RUNTIME_DIAGNOSTICS", True)
    with pytest.raises(KeyboardInterrupt):
        application(app)
    assert metrics.enabled is previous
    import threading
    assert not any(thread.name == "nova-runtime-monitor" for thread in threading.enumerate())


def test_scheduler_poll_failure_waits_then_recovers(measured):
    from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
    recovered = Event()
    calls = []
    def due(now):
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise sqlite3.OperationalError("private SQL")
        recovered.set()
        return []
    scheduler = ReminderScheduler(Mock(get_due_reminders=due), Mock(), interval_seconds=.03)
    scheduler.start()
    try:
        assert recovered.wait(2)
    finally:
        assert scheduler.stop(2)
    assert calls[1] - calls[0] >= .02
    assert measured.snapshot()["counters"]["scheduler_failures"] == 1


def test_recovery_attempts_are_numeric_and_stop_event_avoids_retry(measured):
    from offline_ai_companion.audio.recovery import AudioRecovery
    stop = Event()
    AudioRecovery(retry_delay=0).handle_failure("Microphone", OSError("private"), stop)
    stop.set()
    AudioRecovery(retry_delay=0).handle_failure("Microphone", OSError("private"), stop)
    assert measured.snapshot()["counters"]["audio_recovery_attempts"] == 1


def test_sampler_cannot_add_private_fields_or_nonnumeric_resources():
    sampler = Mock()
    sampler.sample.return_value = {"rss_bytes": "private", "python_threads": 2,
                                   "cpu_percent": math.nan, "command_line": "secret"}
    result = RuntimeMonitor(sampler=sampler).sample()
    assert result["rss_bytes"] is None and result["cpu_percent"] is None
    assert result["python_threads"] == 2
    assert "command_line" not in result and "secret" not in json.dumps(result)


def test_monitor_start_failure_does_not_prevent_application_work(monkeypatch, measured):
    import offline_ai_companion.core.runtime_metrics as runtime
    import offline_ai_companion.config as config
    thread = Mock()
    thread.start.side_effect = RuntimeError("private OS error")
    monkeypatch.setattr(runtime, "Thread", Mock(return_value=thread))
    monkeypatch.setattr(config, "NOVA_RUNTIME_DIAGNOSTICS", True)
    app = SimpleNamespace(runtime_health=lambda: {})
    @runtime.observed_runtime
    def application(app):
        return 42
    assert application(app) == 42
    thread.join.assert_not_called()
    assert measured.snapshot()["counters"]["resource_sample_failures"] == 1


@pytest.mark.parametrize("duration", [math.nan, math.inf, -math.inf])
def test_capture_duration_must_be_finite(duration):
    with pytest.raises(ValueError):
        ContinuousRecorder(max_duration=duration)


def test_fast_backend_cannot_grow_capture_beyond_sample_budget(tmp_path, monkeypatch):
    block = np.full((1600, 1), .1, dtype=np.float32)
    queue = Mock()
    queue.get.return_value = block
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.queue.Queue", Mock(return_value=queue))
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.time.monotonic", lambda: 0.)
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Mock(return_value=stream))
    recorder = ContinuousRecorder(max_duration=.3)
    target = tmp_path / "bounded.wav"
    assert recorder.record_utterance(target) == target
    import soundfile as sf
    assert sf.info(target).frames <= recorder.max_capture_blocks * len(block)
    assert queue.get.call_count <= recorder.max_capture_blocks


def test_worker_can_request_its_own_stop_without_self_join_failure():
    results = []
    worker = None
    def process(text):
        results.append(worker.stop(timeout=0))
        return 0
    worker = PassiveMemoryWorker(Mock(process=process))
    worker.start()
    assert worker.submit("Synthetic accepted speech")
    assert worker.stop(timeout=3)
    assert results == [False] and worker.queue.unfinished_tasks == 0


@pytest.mark.parametrize("enabled", [True, False])
def test_optional_reminder_metrics_never_require_extra_delivery_fields(monkeypatch, enabled):
    from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
    monkeypatch.setattr(metrics, "enabled", enabled)
    reminder = SimpleNamespace(id=1, message="Synthetic reminder")
    repository = Mock()
    repository.get_due_reminders.return_value = [reminder]
    repository.complete_reminder.return_value = True
    deliver = Mock()
    scheduler = ReminderScheduler(repository, deliver)
    assert scheduler.check_due() == 1
    deliver.assert_called_once_with(reminder)
