
from datetime import datetime, timezone
from threading import Event, Thread

import pytest

from offline_ai_companion.memory.models import Reminder
from offline_ai_companion.scheduler.reminder_notifications import (
    ReminderNotifications,
)


def make_reminder(reminder_id: int) -> Reminder:
    return Reminder(
        id=reminder_id,
        message=f"Reminder {reminder_id}",
        remind_at=datetime.now(timezone.utc),
        is_completed=False,
        created_at="2026-10-09",
    )


def test_interrupt_remains_set_for_new_pending_reminder():
    notifications = ReminderNotifications()

    completed = Event()

    def request_reminder():
        notifications.request(make_reminder(1))
        completed.set()

    worker = Thread(target=request_reminder)
    worker.start()

    try:
        assert notifications.interrupt.wait(timeout=2)

        notification = notifications.get_pending()
        assert notification is not None

        # Simulate another reminder being queued while
        # the first notification is being processed.
        second_finished = Event()

        def request_second():
            notifications.request(make_reminder(2))
            second_finished.set()

        second_worker = Thread(target=request_second)
        second_worker.start()

        try:
            # This event must remain set while the
            # second reminder is waiting.
            assert notifications.interrupt.is_set()

            second = notifications.get_pending()
            assert second is not None
            assert second.reminder.id == 2

            notification.finished.set()
            second.finished.set()

            worker.join(timeout=2)
            second_worker.join(timeout=2)

            assert completed.is_set()
            assert second_finished.is_set()

            assert notifications.get_pending() is None
            assert not notifications.interrupt.is_set()
        finally:
            notifications.close()
            second_worker.join(timeout=2)

    finally:
        notifications.close()
        worker.join(timeout=2)


def test_close_rejects_new_requests():
    notifications = ReminderNotifications()
    notifications.close()

    with pytest.raises(
        RuntimeError,
        match="shutting down",
    ):
        notifications.request(make_reminder(1))


def test_close_releases_waiting_request():
    notifications = ReminderNotifications()
    finished = Event()
    errors = []

    def request_reminder():
        try:
            notifications.request(make_reminder(1))
        except RuntimeError as exc:
            errors.append(str(exc))
        finally:
            finished.set()

    worker = Thread(target=request_reminder)
    worker.start()

    try:
        assert notifications.interrupt.wait(timeout=2)

        notifications.close()

        assert finished.wait(timeout=2)
        assert errors == [
            "Reminder delivery interrupted."
        ]

    finally:
        notifications.close()
        worker.join(timeout=2)


def test_empty_queue_clears_interrupt():
    notifications = ReminderNotifications()

    notifications.interrupt.set()

    assert notifications.get_pending() is None
    assert not notifications.interrupt.is_set()


def test_notification_error_is_propagated():
    notifications = ReminderNotifications()
    finished = Event()
    errors = []

    def request_reminder():
        try:
            notifications.request(make_reminder(1))
        except RuntimeError as exc:
            errors.append(str(exc))
        finally:
            finished.set()

    worker = Thread(target=request_reminder)
    worker.start()

    try:
        assert notifications.interrupt.wait(timeout=2)

        notification = notifications.get_pending()
        assert notification is not None

        notification.error = RuntimeError(
            "Audio playback failed"
        )
        notification.finished.set()

        assert finished.wait(timeout=2)
        assert errors == ["Audio playback failed"]

    finally:
        notifications.close()
        worker.join(timeout=2)
