
from threading import Event
from unittest.mock import Mock

import pytest

from offline_ai_companion.memory.passive_worker import (
    PassiveMemoryWorker,
)


def test_worker_processes_transcript():
    processed = Event()

    processor = Mock()
    processor.process.side_effect = (
        lambda transcript: processed.set()
    )

    worker = PassiveMemoryWorker(processor)

    worker.start()

    try:
        assert worker.submit(
            "I have a presentation tomorrow"
        )

        assert processed.wait(timeout=3.0)

        processor.process.assert_called_once_with(
            "I have a presentation tomorrow"
        )

    finally:
        assert worker.stop()


def test_worker_rejects_empty_transcript():
    worker = PassiveMemoryWorker(Mock())

    worker.start()

    try:
        assert worker.submit("  ") is False
        assert worker.submit("") is False

    finally:
        assert worker.stop()


def test_worker_rejects_submission_before_start():
    worker = PassiveMemoryWorker(Mock())

    assert worker.submit("Test transcript") is False


def test_worker_rejects_submission_after_stop():
    worker = PassiveMemoryWorker(Mock())

    worker.start()
    assert worker.stop()

    assert worker.submit("Test transcript") is False


def test_worker_can_start_twice():
    worker = PassiveMemoryWorker(Mock())

    worker.start()
    first_thread = worker.thread

    worker.start()

    assert worker.thread is first_thread

    assert worker.stop()


def test_invalid_queue_size():
    with pytest.raises(ValueError):
        PassiveMemoryWorker(
            processor=Mock(),
            max_queue_size=0,
        )


def test_worker_handles_processor_failure():
    attempted = Event()

    def failing_processor(transcript):
        attempted.set()
        raise RuntimeError("Ollama unavailable")

    processor = Mock()
    processor.process.side_effect = failing_processor

    worker = PassiveMemoryWorker(processor)

    worker.start()

    try:
        assert worker.submit("Test transcript")
        assert attempted.wait(timeout=3.0)

    finally:
        assert worker.stop()


def test_worker_can_restart():
    worker = PassiveMemoryWorker(Mock())

    worker.start()
    assert worker.stop()

    worker.start()

    assert worker.thread.is_alive()
    assert worker.stop()


def test_worker_does_not_invoke_speech():
    processed = Event()

    processor = Mock()
    processor.process.side_effect = (
        lambda transcript: processed.set()
    )

    worker = PassiveMemoryWorker(processor)

    worker.start()

    try:
        assert worker.submit(
            "I need to finish the report"
        )

        assert processed.wait(timeout=3.0)

        # The worker only delegates to the
        # passive processor, never to TTS.
        assert not hasattr(worker, "tts")
        assert not hasattr(worker, "player")

    finally:
        assert worker.stop()


def test_shutdown_drains_queue_after_slow_processing():
    entered = Event()
    release = Event()
    calls = []

    def process(transcript):
        calls.append(transcript)
        if transcript == "First transcript":
            entered.set()
            assert release.wait(3)
        return 1

    processor = Mock()
    processor.process.side_effect = process
    worker = PassiveMemoryWorker(processor)
    worker.start()
    try:
        assert not worker.thread.daemon
        assert worker.submit("First transcript")
        assert entered.wait(3)
        assert worker.submit("Second transcript")
        assert worker.stop(timeout=0) is False
        assert worker.submit("Late transcript") is False
        # Restart while draining must not reopen submissions or create a thread.
        original_thread = worker.thread
        worker.start()
        assert worker.thread is original_thread
        assert worker.submit("Late transcript") is False
    finally:
        release.set()
        assert worker.stop(timeout=3)
    assert calls == ["First transcript", "Second transcript"]
    assert worker.queue.unfinished_tasks == 0
    assert worker.queue.empty()


def test_shutdown_continues_draining_after_processor_failure():
    entered = Event()
    release = Event()
    calls = []

    def process(transcript):
        calls.append(transcript)
        if transcript == "Failing transcript":
            entered.set()
            assert release.wait(3)
            raise RuntimeError("Model unavailable")
        return 1

    processor = Mock()
    processor.process.side_effect = process
    worker = PassiveMemoryWorker(processor)
    worker.start()
    try:
        assert worker.submit("Failing transcript")
        assert entered.wait(3)
        assert worker.submit("Following transcript")
        assert not worker.stop(timeout=0)
    finally:
        release.set()
        assert worker.stop(timeout=3)
    assert calls == ["Failing transcript", "Following transcript"]
    assert worker.queue.unfinished_tasks == 0


@pytest.mark.parametrize("transcript", ["[XBOX SOUND] [MUSIC]", "(applause)", "...", None])
def test_worker_rejects_non_speech_before_queueing(transcript):
    processor = Mock()
    worker = PassiveMemoryWorker(processor)
    worker.start()
    try:
        assert not worker.submit(transcript)
    finally:
        assert worker.stop()
    processor.process.assert_not_called()


def test_negative_stop_timeout_does_not_change_worker_state():
    worker = PassiveMemoryWorker(Mock())
    worker.start()
    try:
        with pytest.raises(ValueError, match="timeout"):
            worker.stop(timeout=-1)
        assert worker.accepting
    finally:
        assert worker.stop()


def test_transcript_arriving_at_get_timeout_is_not_stranded():
    from queue import Empty
    processor = Mock()
    processor.process.return_value = 1
    worker = PassiveMemoryWorker(processor)
    worker.accepting = True
    original_get = worker.queue.get
    first_get = True

    def get_at_shutdown(*args, **kwargs):
        nonlocal first_get
        if first_get:
            first_get = False
            # Model a producer winning the race between get() timing out
            # and the consumer checking the shutdown signal.
            assert worker.submit("Accepted at shutdown")
            assert worker.stop(timeout=0)
            raise Empty
        return original_get(*args, **kwargs)

    worker.queue.get = get_at_shutdown
    worker._run()
    processor.process.assert_called_once_with("Accepted at shutdown")
    assert worker.queue.unfinished_tasks == 0
