
from datetime import datetime, timedelta, timezone

import pytest

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "test.db")
    return MemoryRepository(database)


def test_database_initialization(tmp_path):
    path = tmp_path / "memory.db"
    database = Database(path)

    database.initialize()
    database.initialize()

    assert path.exists()


def test_add_and_list_notes(repository):
    note = repository.add_note("Remember my idea")

    notes = repository.list_notes()

    assert len(notes) == 1
    assert notes[0].id == note.id
    assert notes[0].content == "Remember my idea"


def test_update_note(repository):
    note = repository.add_note("Original")

    assert repository.update_note(note.id, "Updated")
    assert repository.list_notes()[0].content == "Updated"


def test_delete_note(repository):
    note = repository.add_note("Temporary")

    assert repository.delete_note(note.id)
    assert repository.list_notes() == []


def test_empty_note_rejected(repository):
    with pytest.raises(ValueError):
        repository.add_note("   ")


def test_add_and_complete_task(repository):
    task = repository.add_task("Finish project")

    assert not task.is_completed
    assert repository.complete_task(task.id)

    tasks = repository.list_tasks()
    assert tasks[0].is_completed
    assert repository.list_tasks(
        include_completed=False
    ) == []


def test_delete_task(repository):
    task = repository.add_task("Temporary task")

    assert repository.delete_task(task.id)
    assert repository.list_tasks() == []


def test_add_reminder(repository):
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    reminder = repository.add_reminder("Drink water", future)

    assert reminder.message == "Drink water"
    assert reminder.remind_at == future
    assert len(repository.list_reminders()) == 1


def test_due_reminders(repository):
    now = datetime.now(timezone.utc)

    repository.add_reminder(
        "Due",
        now - timedelta(minutes=5),
    )
    repository.add_reminder(
        "Later",
        now + timedelta(hours=1),
    )

    due = repository.get_due_reminders(now)

    assert len(due) == 1
    assert due[0].message == "Due"


def test_complete_reminder(repository):
    past = datetime.now(timezone.utc) - timedelta(minutes=1)

    reminder = repository.add_reminder("Done", past)

    assert repository.complete_reminder(reminder.id)
    assert repository.get_due_reminders() == []


def test_delete_reminder(repository):
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    reminder = repository.add_reminder("Temporary", future)

    assert repository.delete_reminder(reminder.id)
    assert repository.list_reminders() == []


def test_naive_reminder_time_rejected(repository):
    with pytest.raises(ValueError):
        repository.add_reminder(
            "Invalid",
            datetime(2026, 10, 9, 12, 0),
        )


def test_memory_persists_after_reopening(tmp_path):
    path = tmp_path / "persistent.db"

    first = MemoryRepository(Database(path))
    first.add_note("Persistent memory")

    second = MemoryRepository(Database(path))

    assert second.list_notes()[0].content == "Persistent memory"
