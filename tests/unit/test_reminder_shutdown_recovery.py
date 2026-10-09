
from datetime import datetime, timezone
from threading import Event, Thread
from unittest.mock import Mock
import time

import pytest

from offline_ai_companion.scheduler.reminder_notifications import (
    ReminderNotifications,
)
from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)


def make_reminder():
    reminder = Mock()
    reminder.id = 1
    reminder.message = "Drink water"
    return reminder


def test_shutdown_releases_active_notification():
    notifications = ReminderNotifications()
    reminder = make_reminder()
    errors = []

    def requester():
        try:
            notifications.request(reminder)
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = Thread(target=requester)
    thread.start()

    deadline = time.monotonic() + 2

    notification = None
    while time.monotonic() < deadline:
        notification = notifications.get_pending()
        if notification is not None:
            break
        time.sleep(0.01)

    assert notification is not None

    notifications.close()

    thread.join(timeout=2)

    assert not thread.is_alive()
    assert notification.finished.is_set()
    assert notification.error is not None
    assert errors


def test_successful_acknowledgment():
    notifications = ReminderNotifications()
    reminder = make_reminder()
    errors = []

    def requester():
        try:
            notifications.request(reminder)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=requester)
    thread.start()

    deadline = time.monotonic() + 2
    notification = None

    while time.monotonic() < deadline:
        notification = notifications.get_pending()
        if notification is not None:
            break
        time.sleep(0.01)

    assert notification is not None

    notifications.acknowledge(notification)

    thread.join(timeout=2)

    assert not thread.is_alive()
    assert notification.finished.is_set()
    assert notification.error is None
    assert not errors


def test_failed_acknowledgment():
    notifications = ReminderNotifications()
    reminder = make_reminder()
    errors = []

    def requester():
        try:
            notifications.request(reminder)
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = Thread(target=requester)
    thread.start()

    deadline = time.monotonic() + 2
    notification = None

    while time.monotonic() < deadline:
        notification = notifications.get_pending()
        if notification is not None:
            break
        time.sleep(0.01)

    assert notification is not None

    notifications.acknowledge(
        notification,
        error=RuntimeError("Speaker unavailable"),
    )

    thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == ["Speaker unavailable"]


def test_scheduler_database_polling_failure_recovery():
    repository = Mock()
    repository.get_due_reminders.side_effect = [
        RuntimeError("Database temporarily unavailable"),
        [],
    ]

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=Mock(),
        interval_seconds=0.01,
    )

    with pytest.raises(RuntimeError):
        scheduler.check_due()

    assert scheduler.check_due() == 0
    assert repository.get_due_reminders.call_count == 2


def test_scheduler_restart():
    repository = Mock()
    repository.get_due_reminders.return_value = []

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=Mock(),
        interval_seconds=0.01,
    )

    scheduler.start()

    try:
        assert scheduler.is_running
    finally:
        scheduler.stop(timeout=2)

    assert not scheduler.is_running

    scheduler.start()

    try:
        assert scheduler.is_running
    finally:
        scheduler.stop(timeout=2)

    assert not scheduler.is_running
