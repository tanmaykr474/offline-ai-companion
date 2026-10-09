from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Thread

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler


def test_abrupt_process_exit_rolls_back_uncommitted_data(tmp_path):
    database = Database(tmp_path / "durability.db")
    repository = MemoryRepository(database)
    repository.set_fact("user.favorite_language", "Python")
    child = tmp_path / "abrupt.py"
    child.write_text('''import os, sys
from offline_ai_companion.memory.database import Database
with Database(sys.argv[1]).connect() as connection:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE facts SET value = 'Java'")
    connection.execute("INSERT INTO tasks(title) VALUES ('Uncommitted task')")
    os._exit(23)
''', encoding="utf-8")
    result = subprocess.run([sys.executable, str(child), str(database.path)], capture_output=True, timeout=10)
    assert result.returncode == 23
    reopened = MemoryRepository(Database(database.path))
    assert reopened.get_fact("user.favorite_language") == "Python"
    assert reopened.list_tasks() == []
    with database.connect() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_concurrent_schedulers_and_memory_writes_preserve_consistency(tmp_path):
    database = Database(tmp_path / "concurrent.db")
    repository = MemoryRepository(database)
    now = datetime.now(timezone.utc)
    for index in range(12):
        repository.add_reminder(f"Synthetic reminder {index}", now)
    delivered, errors = [], []
    barrier = Barrier(3)
    def guarded(operation):
        try:
            barrier.wait(timeout=5)
            operation()
        except Exception as exc:
            errors.append(exc)
    def writes():
        for index in range(12):
            repository.add_note(f"Synthetic note {index}")
            repository.set_fact("user.favorite_language", "Python")
    schedulers = [ReminderScheduler(repository, lambda reminder: delivered.append(reminder.id), clock=lambda: now)
                  for _ in range(2)]
    threads = [Thread(target=guarded, args=(operation,)) for operation in
               (schedulers[0].check_due, schedulers[1].check_due, writes)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert not any(thread.is_alive() for thread in threads) and errors == []
    assert len(delivered) == len(set(delivered)) == 12
    assert len(repository.list_notes()) == 12
    assert all(reminder.is_completed for reminder in repository.list_reminders())
    with database.connect() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_synthetic_soak_covers_restarts_without_devices_or_real_database():
    path = Path(__file__).resolve().parents[2] / "scripts" / "soak_runtime.py"
    spec = importlib.util.spec_from_file_location("nova_soak_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_soak(cycles=2)
    assert report["invariants_passed"] and report["cycles_completed"] == 2
    assert report["stream_opens"] == report["stream_closes"] > 0
    assert report["python_threads_before"] == report["python_threads_after"]
    assert report["physical_devices_verified"] is False
    assert report["counters"]["passive_failures"] == 2
    assert report["counters"]["audio_recovery_attempts"] == 2
    assert report["counters"]["reminder_completed"] == 2
    assert report["timings"]["ollama_response"]["errors"] >= 2
