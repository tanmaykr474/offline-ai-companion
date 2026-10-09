from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from unittest.mock import Mock
import sqlite3

import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.confirmation import FactConfirmationManager
from offline_ai_companion.router.query_router import QueryRouter
from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
from offline_ai_companion.scheduler.reminder_time import local_timezone, parse_reminder_time
from offline_ai_companion.tools.memory_tools import MemoryTools

NOW = datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc)  # 09:30 Kolkata


@pytest.fixture
def env(tmp_path):
    repo = MemoryRepository(Database(tmp_path / "lifecycle.db"))
    time = [NOW]
    tools = MemoryTools(repo, clock=lambda: time[0], timezone_name="Asia/Kolkata")
    llm = Mock(generate=Mock(return_value="Normal response"))
    assistant = Assistant(memory_tools=tools, llm=llm,
                          fact_extractor=Mock(extract=Mock(return_value=None)))
    return assistant, repo, time, llm


def snapshot(repo):
    with repo.database.connect() as db:
        return {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t}")]
                for t in ("tasks", "reminders", "facts", "notes", "passive_memories")}


@pytest.mark.parametrize("command", ["Add a task to finish my project.", "Create a task to finish my project."])
def test_create_task_explicit_command(env, command):
    assistant, repo, _, llm = env
    assert "task:1" in assistant.process(command)
    assert repo.list_tasks()[0].title == "finish my project"
    llm.generate.assert_not_called()


def test_read_only_paginated_task_list_and_stable_ids(env):
    assistant, repo, _, _ = env
    for i in range(5):
        repo.add_task(f"Project {i}")
    repo.complete_task(2)
    before = snapshot(repo)
    first = assistant.process("Show my pending tasks")
    second = assistant.process("Show my pending tasks page 2")
    assert "task:1" in first and "task:2" not in first and "page 2" in first
    assert "task:5" in second
    assert snapshot(repo) == before


@pytest.mark.parametrize("command", ["Mark my project task as completed.", "Complete task number 1.", "Complete task:1"])
def test_complete_task_requires_confirmation_and_is_idempotent(env, command):
    assistant, repo, _, _ = env
    task = repo.add_task("finish my project")
    unrelated = repo.add_task("read a book")
    assert "Reply Yes or No" in assistant.process(command)
    assert not repo.get_task(task.id).is_completed
    assert "completed" in assistant.process("Yes")
    assert repo.get_task(task.id).is_completed
    assert not repo.get_task(unrelated.id).is_completed
    before = snapshot(repo)
    assert "already completed" in assistant.process(command)
    assert snapshot(repo) == before


@pytest.mark.parametrize("command", ["Delete my project task.", "Delete task number 1.", "Remove task:1"])
def test_delete_task_confirmation_and_other_tables_untouched(env, command):
    assistant, repo, _, _ = env
    repo.add_task("finish my project")
    other = repo.add_task("Other")
    note = repo.add_note("finish my project")
    assert "Confirm delete task:1" in assistant.process(command)
    assert repo.get_task(1)
    assert "Saved" in assistant.process("Yes delete")
    assert repo.get_task(1) is None and repo.get_task(other.id)
    assert repo.list_notes()[0] == note


def test_rename_task_and_recall_list(env):
    assistant, repo, _, _ = env
    repo.add_task("finish my project")
    assert "Confirm rename task:1" in assistant.process("Rename my project task to finish the API integration.")
    assert repo.get_task(1).title == "finish my project"
    assistant.process("Yes")
    assert repo.get_task(1).title == "finish the API integration"
    assert "API integration" in assistant.process("Show my pending tasks")


@pytest.mark.parametrize("command", ["Delete my project task", "Complete my project task",
                                     "Rename my project task to integration"])
def test_ambiguous_tasks_require_id_without_pending(env, command):
    assistant, repo, _, _ = env
    repo.add_task("finish my project")
    repo.add_task("review my project")
    before = snapshot(repo)
    assert "Multiple tasks match" in assistant.process(command)
    assert assistant.task_management.pending is None
    assistant.process("Yes")
    assert snapshot(repo) == before


@pytest.mark.parametrize("question,expected", [
    ("Remind me to call Mom tomorrow at 6 PM.", datetime(2026, 10, 10, 12, 30, tzinfo=timezone.utc)),
    ("Remind me to take a break at 4 PM.", datetime(2026, 10, 9, 10, 30, tzinfo=timezone.utc)),
    ("Remind me about the meeting on October 15 at 10 AM.", datetime(2026, 10, 15, 4, 30, tzinfo=timezone.utc)),
    ("Remind me to drink water in 30 minutes.", NOW + timedelta(minutes=30)),
    ("Remind me to stretch in 2 hours.", NOW + timedelta(hours=2)),
    ("Remind me to check email on 2027-01-15 at 12:05 AM.", datetime(2027, 1, 14, 18, 35, tzinfo=timezone.utc)),
])
def test_reminder_creation_calendar_and_relative(env, question, expected):
    assistant, repo, _, llm = env
    assert "reminder:1" in assistant.process(question)
    assert repo.get_reminder(1).remind_at == expected
    assert repo.get_reminder(1).remind_at.utcoffset() == timedelta(0)
    llm.generate.assert_not_called()


@pytest.mark.parametrize("question", [
    "Remind me in 30 minutes.", "Remind me to call Mom tomorrow.",
    "Remind me to call Mom at 4.", "Remind me to call Mom on 10/15 at 6 PM.",
    "Remind me to call Mom on February 30 at 6 PM.",
    "Remind me to call Mom on October 8 at 6 PM.",
    "Remind me to call Mom at 8 AM.", "Remind me to call Mom at 13 PM.",
    "Remind me to call Mom at 6:70 PM.", "Remind me to call Mom in 0 minutes.",
    "Remind me to call Mom on October 15 2025 at 6 PM.",
])
def test_invalid_incomplete_past_reminders_never_saved(env, question):
    assistant, repo, _, llm = env
    assert "saved:" not in assistant.process(question).lower()
    assert repo.list_reminders() == []
    llm.generate.assert_not_called()


@pytest.mark.parametrize("expression", ["on 2026-03-08 at 2:30 AM", "on 2026-11-01 at 1:30 AM"])
def test_dst_gap_and_fold_rejected(expression):
    with pytest.raises(ValueError, match="daylight-saving"):
        parse_reminder_time(expression, datetime(2026, 1, 1, tzinfo=timezone.utc), local_timezone("America/New_York"))


@pytest.mark.parametrize("expression,expected", [
    ("on 2026-03-08 at 3:30 AM", datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)),
    ("on 2026-11-01 at 2:30 AM", datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)),
    ("on February 29 2028 at 12 PM", datetime(2028, 2, 29, 17, 0, tzinfo=timezone.utc)),
])
def test_valid_dst_and_leap_year(expression, expected):
    assert parse_reminder_time(expression, datetime(2026, 1, 1, tzinfo=timezone.utc),
                               local_timezone("America/New_York")) == expected


def test_relative_delay_is_elapsed_time_across_dst():
    now = datetime(2026, 3, 8, 6, 30, tzinfo=timezone.utc)
    assert parse_reminder_time("in 2 hours", now, local_timezone("America/New_York")) == now + timedelta(hours=2)


def test_clock_local_day_used_not_utc_day():
    now = datetime(2026, 10, 9, 21, 0, tzinfo=timezone.utc)
    assert parse_reminder_time("tomorrow at 6 AM", now, local_timezone("Asia/Kolkata")) == datetime(2026, 10, 10, 0, 30, tzinfo=timezone.utc) + timedelta(days=1)


def test_invalid_timezone_and_naive_clock_fail_clearly():
    with pytest.raises(ValueError, match="REMINDER_TIMEZONE"):
        local_timezone("Invalid/place")
    with pytest.raises(ValueError, match="clock"):
        parse_reminder_time("in 5 minutes", datetime(2026, 1, 1), local_timezone("UTC"))


@pytest.mark.parametrize("command", ["Cancel my reminder to call Mom.", "Delete reminder number 1.", "Delete reminder:1"])
def test_reminder_cancel_delete_confirmed(env, command):
    assistant, repo, _, _ = env
    reminder = repo.add_reminder("call Mom", NOW + timedelta(days=1))
    other = repo.add_reminder("call Dad", NOW + timedelta(days=1))
    assert "Reply Yes or No" in assistant.process(command)
    assert not repo.get_reminder(reminder.id).is_completed
    assistant.process("Yes")
    if command.startswith("Cancel"):
        assert repo.get_reminder(reminder.id).is_completed
    else:
        assert repo.get_reminder(reminder.id) is None
    assert not repo.get_reminder(other.id).is_completed


@pytest.mark.parametrize("completed", [False, True])
def test_snooze_due_or_delivered_reminder_rearms_once(env, completed):
    assistant, repo, time, _ = env
    reminder = repo.add_reminder("take a break", NOW - timedelta(minutes=1))
    if completed:
        repo.complete_reminder(reminder.id)
    assert "Confirm snooze" in assistant.process("Snooze my reminder for 10 minutes.")
    time[0] += timedelta(minutes=1)
    assistant.process("Yes")
    # Delay anchored to the reviewed command, not shifted silently by confirmation.
    assert repo.get_reminder(reminder.id).remind_at == NOW + timedelta(minutes=10)
    assert not repo.get_reminder(reminder.id).is_completed
    received = []
    scheduler = ReminderScheduler(repo, received.append, clock=lambda: NOW + timedelta(minutes=10))
    assert scheduler.check_due() == 1 and scheduler.check_due() == 0
    assert len(received) == 1


def test_reschedule_meeting_and_persistence(env):
    assistant, repo, _, _ = env
    reminder = repo.add_reminder("meeting", NOW + timedelta(hours=1))
    assert "Confirm reschedule" in assistant.process("Reschedule my meeting reminder to tomorrow at 11 AM.")
    assistant.process("Yes")
    restarted = MemoryRepository(Database(repo.database.path))
    assert restarted.get_reminder(reminder.id).remind_at == datetime(2026, 10, 10, 5, 30, tzinfo=timezone.utc)
    assert "meeting" in assistant.process("Show my upcoming reminders")


def test_ambiguous_reminder_no_change(env):
    assistant, repo, _, _ = env
    repo.add_reminder("call Mom", NOW + timedelta(hours=1))
    repo.add_reminder("call Mom about school", NOW + timedelta(hours=2))
    # Exact complete title wins; partial label is ambiguous.
    assert "Confirm cancel" in assistant.process("Cancel my reminder to call Mom")
    assistant.process("No")
    assert "Multiple reminders" in assistant.process("Cancel my call reminder")
    assert all(not r.is_completed for r in repo.list_reminders())


@pytest.mark.parametrize("reply", ["No", "Cancel", "Yes and delete everything", "Yeah", "Go ahead", "Yes rename"])
def test_ambiguous_confirmation_and_cancellation_no_writes(env, reply):
    assistant, repo, _, _ = env
    repo.add_task("project")
    assistant.process("Delete task number 1")
    before = snapshot(repo)
    assistant.process(reply)
    assert snapshot(repo) == before
    assert assistant.task_management.pending is None


def test_confirmation_deadline_restart_and_repeated_command(env):
    assistant, repo, time, _ = env
    repo.add_task("project")
    assistant.process("Delete task number 1")
    time[0] += timedelta(seconds=120)
    assert "expired" in assistant.process("Yes")
    assistant.process("Delete task number 1")
    assert "Reply Yes or No" in assistant.process("Delete task number 1")
    replacement = Assistant(memory_tools=assistant.memory_tools, llm=Mock(), fact_extractor=Mock())
    assert "no pending" in replacement.process("Yes").lower()
    assert repo.get_task(1)


@pytest.mark.parametrize("change", ["rename", "delete", "aba"])
def test_changed_task_snapshot_cancels_confirmation(env, change):
    assistant, repo, _, _ = env
    repo.add_task("project")
    assistant.process("Delete task number 1")
    if change == "delete":
        repo.delete_task(1)
    else:
        repo.rename_task(1, "other")
        if change == "aba":
            repo.rename_task(1, "project")
    assert "reviewed record changed" in assistant.process("Yes")
    if change != "delete":
        assert repo.get_task(1)


def test_confirmation_workflows_mutually_exclusive(env):
    assistant, repo, _, _ = env
    repo.add_task("project")
    assert "Should I save" in assistant.process("My favorite food is pizza")
    assert assistant.confirmation_manager.pending is not None
    assistant.process("Delete task number 1")
    assert assistant.confirmation_manager.pending is None
    assistant.process("Update my birthplace to Delhi")
    assert assistant.task_management.pending is None
    assistant.process("Yes")
    assert repo.get_fact("user.birthplace") == "Delhi" and repo.get_task(1)
    assistant.process("Delete task number 1")
    assistant.process("What is my birthplace?")
    assistant.process("Yes")
    assert repo.get_task(1)


def test_creation_cancels_previous_memory_confirmation(env):
    assistant, repo, _, _ = env
    repo.set_fact("user.name", "Alice")
    assistant.process("Delete all saved facts")
    assistant.process("Add a task to finish my project")
    assistant.process("Yes")
    assert repo.get_fact("user.name") == "Alice"


def test_past_time_at_confirmation_does_not_write(env):
    assistant, repo, time, _ = env
    reminder = repo.add_reminder("break", NOW + timedelta(days=1))
    assistant.process("Snooze reminder number 1 for 1 minute")
    time[0] += timedelta(minutes=1)
    assert "past or due" in assistant.process("Yes")
    assert repo.get_reminder(1) == reminder


def test_transaction_failure_rolls_back(env):
    assistant, repo, _, _ = env
    repo.add_task("project")
    assistant.process("Rename task number 1 to integration")
    before = snapshot(repo)
    with repo.database.connect() as db:
        db.execute("CREATE TRIGGER deny_rename AFTER UPDATE ON tasks BEGIN SELECT RAISE(ABORT, 'denied'); END")
    assert "could not be saved" in assistant.process("Yes")
    assert snapshot(repo) == before


@pytest.mark.parametrize("command", ["Add a task to remember my password is hunter2",
    "Remind me to use my API key sk-12345678901234567890 in 5 minutes",
    "Rename task number 1 to my password is hunter2"])
def test_credential_commands_cancel_pending_without_storage(env, command):
    assistant, repo, _, _ = env
    repo.add_task("project")
    assistant.process("Delete task number 1")
    before = snapshot(repo)
    assert "credential" in assistant.process(command).lower()
    assert assistant.task_management.pending is None
    assert snapshot(repo) == before


def test_legacy_credentials_filtered_from_lists_and_confirmation(env):
    assistant, repo, _, _ = env
    with repo.database.connect() as db:
        db.execute("INSERT INTO tasks(title) VALUES ('my password is hunter2')")
        db.execute("INSERT INTO reminders(message, remind_at) VALUES ('my password is hunter2', ?)",
                   ((NOW + timedelta(hours=1)).isoformat(),))
    assert "hunter2" not in assistant.process("Show my pending tasks")
    assert "hunter2" not in assistant.process("Show my upcoming reminders")
    assert "hunter2" not in assistant.process("Delete task number 1")
    assistant.process("Yes")
    assert repo.get_task(1) is None


def test_passive_task_event_observations_never_schedule(env):
    assistant, repo, _, llm = env
    llm.generate.return_value = '{"memories": []}'
    processor = PassiveMemoryProcessor(assistant.passive_memory_repository, llm)
    processor.process("I need to finish my project.", captured_at=NOW)
    assert repo.list_tasks() == [] and repo.list_reminders() == []


def test_competing_schedulers_claim_once_and_block_user_mutations(env):
    assistant, repo, _, _ = env
    reminder = repo.add_reminder("meeting", NOW - timedelta(minutes=1))
    assistant.process("Cancel reminder number 1")
    entered, release = Event(), Event()
    results, calls = [], []
    def deliver(item):
        calls.append(item.id)
        entered.set()
        assert release.wait(3)
    first = ReminderScheduler(repo, deliver, clock=lambda: NOW)
    second_repo = MemoryRepository(Database(repo.database.path))
    second = ReminderScheduler(second_repo, calls.append, clock=lambda: NOW)
    thread = Thread(target=lambda: results.append(first.check_due()))
    thread.start()
    try:
        assert entered.wait(3)
        assert second.check_due() == 0
        assert "record changed" in assistant.process("Yes")
        assert "delivery is in progress" in assistant.process("Snooze reminder number 1 for 10 minutes")
        assert repo.delete_reminder(reminder.id) is False
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and results == [1] and calls == [reminder.id]
    assert second.check_due() == 0


def test_stale_due_snapshot_cannot_claim_rescheduled_version(env):
    _, repo, _, _ = env
    reminder = repo.add_reminder("meeting", NOW - timedelta(minutes=1))
    stale = repo.get_due_reminders(NOW)[0]
    repo.reschedule_reminder(reminder.id, NOW + timedelta(days=1))
    assert repo.claim_reminder(stale, NOW) is None
    # Even changing back to the same time must invalidate the old version.
    repo.reschedule_reminder(reminder.id, reminder.remind_at)
    assert repo.claim_reminder(stale, NOW) is None


def test_claim_recovery_after_expiry_and_old_owner_cannot_finalize(env):
    _, repo, _, _ = env
    reminder = repo.add_reminder("break", NOW - timedelta(minutes=1))
    token = repo.claim_reminder(reminder, NOW, lease_seconds=30)
    assert token and repo.claim_reminder(repo.get_due_reminders(NOW)[0], NOW) is None
    restarted = MemoryRepository(Database(repo.database.path))
    recovered = restarted.get_due_reminders(NOW + timedelta(seconds=30))[0]
    replacement = restarted.claim_reminder(recovered, NOW + timedelta(seconds=30))
    assert replacement and replacement != token
    assert not repo.finish_reminder_delivery(reminder.id, token, True)
    assert restarted.finish_reminder_delivery(reminder.id, replacement, True)
    assert restarted.get_due_reminders(NOW + timedelta(days=1)) == []


def test_failed_notification_releases_claim_and_can_retry(env):
    _, repo, _, _ = env
    reminder = repo.add_reminder("break", NOW - timedelta(minutes=1))
    callback = Mock(side_effect=[RuntimeError("speaker unavailable"), None])
    scheduler = ReminderScheduler(repo, callback, clock=lambda: NOW)
    assert scheduler.check_due() == 0
    assert repo.get_due_reminders(NOW)[0].id == reminder.id
    assert scheduler.check_due() == 1


def test_pending_reminder_modified_by_delivery_cannot_delete(env):
    assistant, repo, _, _ = env
    reminder = repo.add_reminder("break", NOW - timedelta(minutes=1))
    assistant.process("Delete reminder number 1")
    assert ReminderScheduler(repo, lambda r: None, clock=lambda: NOW).check_due() == 1
    assert "reviewed record changed" in assistant.process("Yes")
    assert repo.get_reminder(reminder.id).is_completed


def test_upcoming_list_is_read_only_and_marks_due(env):
    assistant, repo, _, _ = env
    repo.add_reminder("due break", NOW - timedelta(minutes=1))
    repo.add_reminder("future meeting", NOW + timedelta(days=1))
    repo.add_reminder("done", NOW - timedelta(minutes=1))
    repo.complete_reminder(3)
    before = snapshot(repo)
    answer = assistant.process("Show my upcoming reminders")
    assert "reminder:1" in answer and "(due)" in answer
    assert "reminder:2" in answer and "(upcoming)" in answer and "IST" in answer
    assert "reminder:3" not in answer
    assert snapshot(repo) == before


@pytest.mark.parametrize("command", ["Complete task number 3", "Rename my project task to API integration",
    "Delete task number 3", "Remind me to call Mom tomorrow at 6 PM", "Show my upcoming reminders",
    "Cancel my reminder to call Mom", "Snooze my reminder for 10 minutes", "Reschedule my meeting reminder to tomorrow at 11 AM"])
def test_extended_commands_route_deterministically(command):
    assert QueryRouter().route(command).intent == "lifecycle_management"


def test_expiry_rechecked_inside_transaction(env):
    assistant, repo, time, _ = env
    repo.add_task("project")
    assistant.process("Delete task number 1")
    time[0] += timedelta(seconds=120)
    assert "expired" in assistant.process("Yes")
    assert repo.get_task(1)


def test_existing_schema_migrates_without_data_or_id_loss(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            is_completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT NOT NULL,
            remind_at TEXT NOT NULL, is_completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO tasks(id, title, is_completed) VALUES (3, 'old project', 1);
        """)
        db.execute("INSERT INTO reminders(id, message, remind_at) VALUES (5, 'old meeting', ?)",
                   ((NOW + timedelta(days=1)).isoformat(),))
    repo = MemoryRepository(Database(path))
    assert repo.get_task(3).title == "old project" and repo.get_task(3).is_completed
    assert repo.get_reminder(5).message == "old meeting" and repo.get_reminder(5).revision == 0
    assert repo.add_task("new").id == 4
    assert repo.add_reminder("new", NOW + timedelta(days=1)).id == 6
    MemoryRepository(Database(path))  # migration is repeatable


def test_restart_preserves_task_completion_rename_and_reminder_delivery(env):
    assistant, repo, _, _ = env
    repo.add_task("project")
    assistant.process("Rename task number 1 to integration")
    assistant.process("Yes")
    assistant.process("Complete task number 1")
    assistant.process("Yes")
    repo.add_reminder("break", NOW - timedelta(minutes=1))
    assert ReminderScheduler(repo, lambda r: None, clock=lambda: NOW).check_due() == 1
    restarted = MemoryRepository(Database(repo.database.path))
    assert restarted.get_task(1).title == "integration" and restarted.get_task(1).is_completed
    announced = []
    assert ReminderScheduler(restarted, announced.append, clock=lambda: NOW).check_due() == 0
    assert announced == []


def test_long_pending_notification_renews_claim_across_initial_expiry(env, monkeypatch):
    _, repo, _, _ = env
    repo.add_reminder("break", datetime.now(timezone.utc) - timedelta(minutes=1))
    entered, renewed, release = Event(), Event(), Event()
    count = [0]
    original = repo.renew_reminder_delivery
    def renew(*args):
        result = original(*args)
        count[0] += 1
        if count[0] >= 4:
            renewed.set()
        return result
    monkeypatch.setattr(repo, "renew_reminder_delivery", renew)
    announced = []
    def deliver(item):
        announced.append(item.id)
        entered.set()
        assert release.wait(3)
    first = ReminderScheduler(repo, deliver, delivery_lease_seconds=0.3)
    second = ReminderScheduler(MemoryRepository(Database(repo.database.path)), announced.append)
    thread = Thread(target=first.check_due)
    thread.start()
    try:
        assert entered.wait(3) and renewed.wait(3)
        assert second.check_due() == 0
        assert announced == [1]
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()


def test_user_deletion_between_due_read_and_claim_prevents_notification(env, monkeypatch):
    assistant, repo, _, _ = env
    repo.add_reminder("break", NOW - timedelta(minutes=1))
    original = repo.get_due_reminders
    def read_then_delete(now):
        rows = original(now)
        assistant.process("Delete reminder number 1")
        assistant.process("Yes")
        return rows
    monkeypatch.setattr(repo, "get_due_reminders", read_then_delete)
    callback = Mock()
    assert ReminderScheduler(repo, callback, clock=lambda: NOW).check_due() == 0
    callback.assert_not_called()


def test_failed_reminder_mutation_rolls_back_original_schedule(env):
    assistant, repo, _, _ = env
    repo.add_reminder("meeting", NOW + timedelta(days=1))
    assistant.process("Reschedule reminder number 1 to tomorrow at 11 AM")
    before = snapshot(repo)
    with repo.database.connect() as db:
        db.execute("CREATE TRIGGER deny_change AFTER UPDATE ON reminders BEGIN SELECT RAISE(ABORT, 'denied'); END")
    assert "could not be saved" in assistant.process("Yes")
    assert snapshot(repo) == before


def test_due_delivery_failure_logs_only_categories(env, caplog):
    _, repo, _, _ = env
    message = "private family appointment"
    repo.add_reminder(message, NOW - timedelta(minutes=1))
    callback = Mock(side_effect=RuntimeError(message))
    assert ReminderScheduler(repo, callback, clock=lambda: NOW).check_due() == 0
    assert message not in caplog.text and "RuntimeError" in caplog.text


def test_completed_cancel_is_idempotent_and_invalid_reschedule_read_only(env):
    assistant, repo, _, _ = env
    reminder = repo.add_reminder("meeting", NOW + timedelta(days=1))
    repo.complete_reminder(reminder.id)
    before = snapshot(repo)
    assert "already inactive" in assistant.process("Cancel reminder number 1")
    assert "Specify" in assistant.process("Reschedule reminder number 1 to tomorrow")
    assert snapshot(repo) == before


@pytest.mark.parametrize("kind", ["task", "reminder"])
def test_wrong_numeric_id_does_not_touch_other_table(env, kind):
    assistant, repo, _, _ = env
    repo.add_note("private note")
    if kind == "task":
        repo.add_reminder("meeting", NOW + timedelta(days=1))
    else:
        repo.add_task("project")
    before = snapshot(repo)
    assert "No matching" in assistant.process(f"Delete {kind} number 1")
    assistant.process("Yes")
    assert snapshot(repo) == before


def test_upcoming_reminder_pagination_and_completed_exclusion(env):
    assistant, repo, _, _ = env
    for i in range(5):
        repo.add_reminder(f"meeting {i}", NOW + timedelta(hours=i + 1))
    repo.complete_reminder(2)
    first = assistant.process("Show my upcoming reminders")
    second = assistant.process("Show my upcoming reminders page 2")
    assert "page 2" in first and "reminder:2" not in first and "reminder:5" in second


def test_interrupted_delivery_releases_claim_for_restart(env):
    _, repo, _, _ = env
    repo.add_reminder("break", NOW - timedelta(minutes=1))
    scheduler = ReminderScheduler(repo, Mock(side_effect=KeyboardInterrupt), clock=lambda: NOW)
    with pytest.raises(KeyboardInterrupt):
        scheduler.check_due()
    recovered = repo.get_due_reminders(NOW)[0]
    token = repo.claim_reminder(recovered, NOW)
    assert token
    assert repo.finish_reminder_delivery(recovered.id, token, False)


def test_reminder_title_containing_task_does_not_route_to_task_table(env):
    assistant, repo, _, _ = env
    task = repo.add_task("reminder finish project")
    reminder = repo.add_reminder("finish my project task", NOW + timedelta(days=1))
    assert "Confirm delete reminder:1" in assistant.process("Delete my reminder to finish my project task")
    assistant.process("Yes")
    assert repo.get_reminder(reminder.id) is None and repo.get_task(task.id)


def test_task_title_containing_reminder_does_not_route_to_reminder_table(env):
    assistant, repo, _, _ = env
    task = repo.add_task("write a reminder")
    reminder = repo.add_reminder("write a reminder", NOW + timedelta(days=1))
    assert "Confirm delete task:1" in assistant.process("Delete my write a reminder task")
    assistant.process("Yes")
    assert repo.get_task(task.id) is None and repo.get_reminder(reminder.id)
