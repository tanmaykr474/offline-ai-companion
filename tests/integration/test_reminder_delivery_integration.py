
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from unittest.mock import Mock, patch

import pytest

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.scheduler.reminder_notifications import (
    ReminderNotifications,
)
from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)

# Load the application script by path because scripts/
# is not an installed Python package.
import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "always_on_assistant.py"

spec = importlib.util.spec_from_file_location(
    "always_on_assistant",
    SCRIPT_PATH,
)

if spec is None or spec.loader is None:
    raise ImportError(f"Cannot load {SCRIPT_PATH}")

if spec.name in sys.modules:
    module = sys.modules[spec.name]
else:
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

AlwaysOnAssistant = module.AlwaysOnAssistant


@pytest.fixture
def environment(tmp_path):
    repository = MemoryRepository(
        Database(tmp_path / "reminders.db")
    )
    notifications = ReminderNotifications()

    # Use the real reminder-delivery method, but mock
    # speech synthesis and playback.
    app = AlwaysOnAssistant.__new__(AlwaysOnAssistant)
    app.notifications = notifications
    app.stop_event = Event()
    app.reminder_output_path = tmp_path / "reminder.wav"
    app.speak = Mock()

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=notifications.request,
        interval_seconds=0.01,
        completion_retries=2,
        completion_retry_delay=0,
    )

    yield {
        "repository": repository,
        "notifications": notifications,
        "app": app,
        "scheduler": scheduler,
    }

    # Always release blocked notification requests.
    notifications.close()
    scheduler.stop(timeout=2.0)


def add_due_reminder(repository, message="Drink water"):
    return repository.add_reminder(
        message,
        datetime.now(timezone.utc) - timedelta(seconds=5),
    )


def pending_messages(repository):
    return [
        reminder.message
        for reminder in repository.get_due_reminders(
            datetime.now(timezone.utc)
        )
    ]


def run_check_in_thread(scheduler):
    finished = Event()
    result = {}

    def worker():
        try:
            result["delivered"] = scheduler.check_due()
        except Exception as exc:
            result["error"] = exc
        finally:
            finished.set()

    thread = Thread(target=worker, daemon=True)
    thread.start()

    return thread, finished, result


def wait_for_interrupt(notifications):
    assert notifications.interrupt.wait(timeout=2.0), (
        "Reminder was not queued in time."
    )


def test_successful_reminder_delivery(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    app = environment["app"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository)

    thread, finished, result = run_check_in_thread(scheduler)

    try:
        wait_for_interrupt(notifications)

        # The scheduler must wait for acknowledgment.
        assert not finished.is_set()
        assert "Drink water" in pending_messages(repository)

        app.deliver_pending_reminders()

        assert finished.wait(timeout=2.0)
        assert result["delivered"] == 1

        app.speak.assert_called_once_with(
            "Reminder: Drink water",
            app.reminder_output_path,
        )

        assert "Drink water" not in pending_messages(repository)

    finally:
        notifications.close()
        thread.join(timeout=2.0)


def test_failed_speech_keeps_reminder_pending(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    app = environment["app"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository, "Take medicine")

    app.speak.side_effect = RuntimeError(
        "Speaker unavailable"
    )

    thread, finished, result = run_check_in_thread(scheduler)

    try:
        wait_for_interrupt(notifications)

        app.deliver_pending_reminders()

        assert finished.wait(timeout=2.0)
        assert result["delivered"] == 0

        assert "Take medicine" in pending_messages(repository)

    finally:
        notifications.close()
        thread.join(timeout=2.0)


def test_failed_reminder_can_be_retried(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    app = environment["app"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository, "Check the oven")

    app.speak.side_effect = RuntimeError(
        "Temporary playback failure"
    )

    first_thread, first_finished, first_result = (
        run_check_in_thread(scheduler)
    )

    try:
        wait_for_interrupt(notifications)
        app.deliver_pending_reminders()

        assert first_finished.wait(timeout=2.0)
        assert first_result["delivered"] == 0

        assert "Check the oven" in pending_messages(repository)

        # Simulate restored audio.
        app.speak.side_effect = None

        second_thread, second_finished, second_result = (
            run_check_in_thread(scheduler)
        )

        wait_for_interrupt(notifications)
        app.deliver_pending_reminders()

        assert second_finished.wait(timeout=2.0)
        assert second_result["delivered"] == 1

        assert "Check the oven" not in pending_messages(repository)

    finally:
        notifications.close()
        first_thread.join(timeout=2.0)
        if "second_thread" in locals():
            second_thread.join(timeout=2.0)


def test_reminder_sets_microphone_interrupt(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository)

    thread, finished, result = run_check_in_thread(scheduler)

    try:
        wait_for_interrupt(notifications)

        assert notifications.interrupt.is_set()

        # Shutdown releases the waiting scheduler.
        notifications.close()

        assert finished.wait(timeout=2.0)
        assert result["delivered"] == 0

    finally:
        notifications.close()
        thread.join(timeout=2.0)


def test_shutdown_releases_queued_reminder(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository, "Queued reminder")

    thread, finished, result = run_check_in_thread(scheduler)

    try:
        wait_for_interrupt(notifications)

        notifications.close()

        assert finished.wait(timeout=2.0)
        assert result["delivered"] == 0

        assert "Queued reminder" in pending_messages(repository)

    finally:
        notifications.close()
        thread.join(timeout=2.0)


def test_shutdown_releases_active_reminder(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository, "Active reminder")

    thread, finished, result = run_check_in_thread(scheduler)

    try:
        wait_for_interrupt(notifications)

        notification = notifications.get_pending()
        assert notification is not None

        # The reminder has been taken from the queue,
        # but speech has not finished.
        assert not finished.is_set()

        notifications.close()

        assert finished.wait(timeout=2.0)
        assert result["delivered"] == 0

        assert "Active reminder" in pending_messages(repository)

    finally:
        notifications.close()
        thread.join(timeout=2.0)


def test_completed_reminder_not_delivered_twice(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    app = environment["app"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository, "Stand up")

    thread, finished, result = run_check_in_thread(scheduler)

    try:
        wait_for_interrupt(notifications)
        app.deliver_pending_reminders()

        assert finished.wait(timeout=2.0)
        assert result["delivered"] == 1

        # A second poll must find no due reminders.
        assert scheduler.check_due() == 0
        assert app.speak.call_count == 1

    finally:
        notifications.close()
        thread.join(timeout=2.0)


def test_scheduler_background_thread_delivers_reminder(environment):
    repository = environment["repository"]
    notifications = environment["notifications"]
    app = environment["app"]
    scheduler = environment["scheduler"]

    add_due_reminder(repository, "Background reminder")

    try:
        scheduler.start()

        wait_for_interrupt(notifications)

        assert scheduler.is_running

        app.deliver_pending_reminders()

        # Wait for the SQLite completion to become visible.
        import time

        deadline = time.monotonic() + 2.0

        while (
            "Background reminder" in pending_messages(repository)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert "Background reminder" not in pending_messages(
            repository
        )

        assert scheduler.stop(timeout=2.0)
        assert not scheduler.is_running

    finally:
        notifications.close()
        scheduler.stop(timeout=2.0)
