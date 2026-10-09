
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)


@pytest.fixture
def repository(tmp_path):
    return MemoryRepository(
        Database(tmp_path / "reminders.db")
    )


@pytest.fixture
def now():
    return datetime(
        2026, 10, 9, 10, 0,
        tzinfo=timezone.utc,
    )


def test_delivers_due_reminder(repository, now):
    reminder = repository.add_reminder(
        "Drink water",
        now - timedelta(minutes=1),
    )

    received = []

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=received.append,
        clock=lambda: now,
    )

    assert scheduler.check_due() == 1
    assert [item.id for item in received] == [
        reminder.id
    ]

    assert repository.get_due_reminders(now) == []


def test_future_reminder_not_delivered(repository, now):
    repository.add_reminder(
        "Attend meeting",
        now + timedelta(minutes=5),
    )

    received = []

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=received.append,
        clock=lambda: now,
    )

    assert scheduler.check_due() == 0
    assert received == []


def test_reminder_not_delivered_twice(repository, now):
    repository.add_reminder(
        "Take a break",
        now - timedelta(seconds=10),
    )

    received = []

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=received.append,
        clock=lambda: now,
    )

    assert scheduler.check_due() == 1
    assert scheduler.check_due() == 0
    assert len(received) == 1


def test_failed_delivery_can_retry(repository, now):
    repository.add_reminder(
        "Check email",
        now - timedelta(minutes=1),
    )

    attempts = []

    def callback(reminder):
        attempts.append(reminder.id)

        if len(attempts) == 1:
            raise RuntimeError("Speaker unavailable")

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=callback,
        clock=lambda: now,
    )

    assert scheduler.check_due() == 0
    assert len(repository.get_due_reminders(now)) == 1

    assert scheduler.check_due() == 1
    assert len(attempts) == 2


def test_scheduler_runs_in_background(repository):
    delivered = Event()

    repository.add_reminder(
        "Background test",
        datetime.now(timezone.utc)
        - timedelta(seconds=1),
    )

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=lambda reminder: delivered.set(),
        interval_seconds=0.05,
    )

    try:
        scheduler.start()

        assert scheduler.is_running
        assert delivered.wait(timeout=2.0)
    finally:
        scheduler.stop()

    assert not scheduler.is_running


def test_invalid_polling_interval(repository):
    with pytest.raises(ValueError):
        ReminderScheduler(
            repository=repository,
            on_reminder=lambda reminder: None,
            interval_seconds=0,
        )
