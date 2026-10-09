
from datetime import datetime, timezone
from threading import Thread
import time

import pytest

from offline_ai_companion.memory.models import Reminder
from offline_ai_companion.scheduler.reminder_notifications import (
    ReminderNotifications,
)


def make_reminder():
    return Reminder(
        id=1,
        message="Drink water",
        remind_at=datetime.now(timezone.utc),
        is_completed=False,
        created_at="2026-10-09",
    )


def test_notification_waits_for_delivery():
    notifications = ReminderNotifications()
    reminder = make_reminder()
    completed = []

    worker = Thread(
        target=lambda: (
            notifications.request(reminder),
            completed.append(True),
        )
    )

    worker.start()

    try:
        deadline = time.monotonic() + 2
        notification = None

        while time.monotonic() < deadline:
            notification = notifications.get_pending()
            if notification is not None:
                break
            time.sleep(0.01)

        assert notification is not None
        assert notifications.interrupt.is_set()
        assert completed == []

        notification.finished.set()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert completed == [True]
    finally:
        notifications.close()
        worker.join(timeout=2)


def test_failed_delivery_propagates_error():
    notifications = ReminderNotifications()
    reminder = make_reminder()
    errors = []

    def request():
        try:
            notifications.request(reminder)
        except RuntimeError as exc:
            errors.append(str(exc))

    worker = Thread(target=request)
    worker.start()

    try:
        deadline = time.monotonic() + 2
        notification = None

        while time.monotonic() < deadline:
            notification = notifications.get_pending()
            if notification is not None:
                break
            time.sleep(0.01)

        assert notification is not None

        notification.error = RuntimeError(
            "Speaker unavailable"
        )
        notification.finished.set()

        worker.join(timeout=2)

        assert errors == ["Speaker unavailable"]
    finally:
        notifications.close()
        worker.join(timeout=2)


def test_shutdown_releases_pending_request():
    notifications = ReminderNotifications()
    reminder = make_reminder()
    errors = []

    def request():
        try:
            notifications.request(reminder)
        except RuntimeError as exc:
            errors.append(str(exc))

    worker = Thread(target=request)
    worker.start()

    try:
        deadline = time.monotonic() + 2

        while (
            notifications.pending.empty()
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert not notifications.pending.empty()

        notifications.close()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert errors == [
            "Reminder delivery interrupted."
        ]
    finally:
        notifications.close()
        worker.join(timeout=2)
