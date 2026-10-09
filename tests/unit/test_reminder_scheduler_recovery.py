
from datetime import datetime, timezone
from threading import Event
from unittest.mock import Mock

import pytest

from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)


def make_reminder():
    reminder = Mock()
    reminder.id = 1
    reminder.message = "Drink water"
    return reminder


def make_scheduler(repository, callback=None, **kwargs):
    return ReminderScheduler(
        repository=repository,
        on_reminder=callback or Mock(),
        interval_seconds=0.01,
        clock=lambda: datetime.now(timezone.utc),
        **kwargs,
    )


def test_completion_recovers_after_temporary_failure():
    repository = Mock()
    reminder = make_reminder()

    repository.get_due_reminders.return_value = [reminder]
    repository.complete_reminder.side_effect = [
        RuntimeError("SQLite temporarily locked"),
        True,
    ]

    callback = Mock()

    scheduler = make_scheduler(
        repository,
        callback,
        completion_retries=3,
        completion_retry_delay=0,
    )

    assert scheduler.check_due() == 1

    callback.assert_called_once_with(reminder)
    assert repository.complete_reminder.call_count == 2


def test_completion_failure_does_not_crash_scheduler():
    repository = Mock()
    reminder = make_reminder()

    repository.get_due_reminders.return_value = [reminder]
    repository.complete_reminder.side_effect = RuntimeError(
        "Database unavailable"
    )

    scheduler = make_scheduler(
        repository,
        completion_retries=3,
        completion_retry_delay=0,
    )

    assert scheduler.check_due() == 0
    assert repository.complete_reminder.call_count == 3


def test_false_completion_result_is_not_retried():
    repository = Mock()
    reminder = make_reminder()

    repository.get_due_reminders.return_value = [reminder]
    repository.complete_reminder.return_value = False

    scheduler = make_scheduler(
        repository,
        completion_retries=3,
        completion_retry_delay=0,
    )

    assert scheduler.check_due() == 0
    repository.complete_reminder.assert_called_once_with(1)


def test_notification_failure_does_not_complete_reminder():
    repository = Mock()
    reminder = make_reminder()

    repository.get_due_reminders.return_value = [reminder]

    callback = Mock(
        side_effect=RuntimeError("Speaker unavailable")
    )

    scheduler = make_scheduler(
        repository,
        callback,
    )

    assert scheduler.check_due() == 0
    repository.complete_reminder.assert_not_called()


def test_stop_before_start():
    scheduler = make_scheduler(Mock())

    assert scheduler.stop() is True
    assert scheduler.is_running is False


def test_stop_rejects_negative_timeout():
    scheduler = make_scheduler(Mock())

    with pytest.raises(ValueError):
        scheduler.stop(timeout=-1)


def test_invalid_retry_configuration():
    with pytest.raises(ValueError):
        make_scheduler(
            Mock(),
            completion_retries=0,
        )

    with pytest.raises(ValueError):
        make_scheduler(
            Mock(),
            completion_retry_delay=-1,
        )


def test_scheduler_stops_successfully():
    repository = Mock()
    repository.get_due_reminders.return_value = []

    scheduler = make_scheduler(repository)

    scheduler.start()

    assert scheduler.is_running is True
    assert scheduler.stop(timeout=2) is True
    assert scheduler.is_running is False


def test_stop_interrupts_completion_retry_delay():
    repository = Mock()
    reminder = make_reminder()
    first_attempt = Event()

    repository.get_due_reminders.return_value = [reminder]

    def fail_completion(reminder_id):
        first_attempt.set()
        raise RuntimeError("Database locked")

    repository.complete_reminder.side_effect = fail_completion

    scheduler = make_scheduler(
        repository,
        completion_retries=5,
        completion_retry_delay=10,
    )

    scheduler.start()

    try:
        assert first_attempt.wait(timeout=2)
        assert scheduler.stop(timeout=2) is True
        assert scheduler.is_running is False
    finally:
        scheduler.stop(timeout=2)
