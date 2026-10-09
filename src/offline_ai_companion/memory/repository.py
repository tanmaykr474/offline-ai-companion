
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from contextlib import nullcontext

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.models import Note, Task, Reminder
from offline_ai_companion.core.privacy_policy import require_safe_storage


class MemoryRepository:
    """Persistent CRUD operations for companion memory."""

    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()

    @staticmethod
    def _validate(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{field} cannot be empty.")
        require_safe_storage(value)
        return value

    @staticmethod
    def _note(row) -> Note:
        return Note(row["id"], row["content"], row["created_at"])

    @staticmethod
    def _task(row) -> Task:
        return Task(
            row["id"],
            row["title"],
            bool(row["is_completed"]),
            row["created_at"],
        )

    @staticmethod
    def _reminder(row) -> Reminder:
        return Reminder(
            row["id"],
            row["message"],
            datetime.fromisoformat(row["remind_at"]),
            bool(row["is_completed"]),
            row["created_at"],
            row["revision"],
        )

    # ---------- NOTES ----------

    def add_note(self, content: str) -> Note:
        content = self._validate(content, "Note")

        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO notes (content) VALUES (?)",
                (content,),
            )
            row = db.execute(
                "SELECT * FROM notes WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._note(row)

    def list_notes(self) -> list[Note]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT * FROM notes ORDER BY id DESC"
            ).fetchall()
            return [self._note(row) for row in rows]

    def update_note(self, note_id: int, content: str) -> bool:
        content = self._validate(content, "Note")
        with self.database.connect() as db:
            result = db.execute(
                "UPDATE notes SET content = ? WHERE id = ?",
                (content, note_id),
            )
            return result.rowcount > 0

    def delete_note(self, note_id: int) -> bool:
        with self.database.connect() as db:
            result = db.execute(
                "DELETE FROM notes WHERE id = ?",
                (note_id,),
            )
            return result.rowcount > 0

    # ---------- TASKS ----------

    def add_task(self, title: str) -> Task:
        title = self._validate(title, "Task")

        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO tasks (title) VALUES (?)",
                (title,),
            )
            row = db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._task(row)

    def list_tasks(
        self,
        include_completed: bool = True,
    ) -> list[Task]:
        query = "SELECT * FROM tasks"
        if not include_completed:
            query += " WHERE is_completed = 0"
        query += " ORDER BY id DESC"

        with self.database.connect() as db:
            rows = db.execute(query).fetchall()
            return [self._task(row) for row in rows]

    def complete_task(self, task_id: int, connection=None) -> bool:
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            result = db.execute(
                "UPDATE tasks SET revision = revision + (1 - is_completed), is_completed = 1 WHERE id = ?",
                (task_id,),
            )
            return result.rowcount > 0

    def delete_task(self, task_id: int, connection=None) -> bool:
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            result = db.execute(
                "DELETE FROM tasks WHERE id = ?",
                (task_id,),
            )
            return result.rowcount > 0

    def get_task(self, task_id: int) -> Task | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._task(row) if row else None

    def rename_task(self, task_id: int, title: str, connection=None) -> bool:
        title = self._validate(title, "Task")
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            return db.execute("UPDATE tasks SET title = ?, revision = revision + 1 WHERE id = ?",
                              (title, task_id)).rowcount > 0

    # ---------- REMINDERS ----------

    def add_reminder(
        self,
        message: str,
        remind_at: datetime,
    ) -> Reminder:
        message = self._validate(message, "Reminder")

        if remind_at.tzinfo is None or remind_at.utcoffset() is None:
            raise ValueError("Reminder time must include a timezone.")

        when = remind_at.astimezone(timezone.utc).isoformat()

        with self.database.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO reminders (message, remind_at)
                VALUES (?, ?)
                """,
                (message, when),
            )
            row = db.execute(
                "SELECT * FROM reminders WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._reminder(row)

    def list_reminders(self) -> list[Reminder]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT * FROM reminders ORDER BY remind_at ASC"
            ).fetchall()
            return [self._reminder(row) for row in rows]

    def get_due_reminders(
        self,
        now: datetime | None = None,
    ) -> list[Reminder]:
        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Current time must include a timezone.")

        cutoff = now.astimezone(timezone.utc).isoformat()

        with self.database.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM reminders
                WHERE is_completed = 0 AND remind_at <= ?
                ORDER BY remind_at ASC
                """,
                (cutoff,),
            ).fetchall()
            return [self._reminder(row) for row in rows]

    def complete_reminder(self, reminder_id: int) -> bool:
        with self.database.connect() as db:
            result = db.execute(
                """
                UPDATE reminders SET revision = revision + (1 - is_completed), is_completed = 1
                WHERE id = ? AND delivery_token IS NULL
                """,
                (reminder_id,),
            )
            return result.rowcount > 0

    def delete_reminder(self, reminder_id: int, connection=None) -> bool:
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            result = db.execute(
                "DELETE FROM reminders WHERE id = ? AND delivery_token IS NULL",
                (reminder_id,),
            )
            return result.rowcount > 0

    def get_reminder(self, reminder_id: int) -> Reminder | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            return self._reminder(row) if row else None

    def reschedule_reminder(self, reminder_id: int, when: datetime, connection=None) -> bool:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("Reminder time must include a timezone.")
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            return db.execute("""UPDATE reminders SET remind_at = ?, is_completed = 0,
                revision = revision + 1 WHERE id = ? AND delivery_token IS NULL""",
                (when.astimezone(timezone.utc).isoformat(), reminder_id)).rowcount > 0

    def cancel_reminder(self, reminder_id: int, connection=None) -> bool:
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            return db.execute("""UPDATE reminders SET is_completed = 1,
                revision = revision + (1 - is_completed)
                WHERE id = ? AND delivery_token IS NULL""", (reminder_id,)).rowcount > 0

    def claim_reminder(self, reminder: Reminder, now: datetime, lease_seconds: int = 300) -> str | None:
        """Atomically claim this exact due version across scheduler instances."""
        if now.tzinfo is None or now.utcoffset() is None or lease_seconds <= 0:
            raise ValueError("A timezone-aware clock and positive delivery lease are required.")
        now = now.astimezone(timezone.utc)
        token = uuid4().hex
        with self.database.connect() as db:
            changed = db.execute("""UPDATE reminders SET delivery_token = ?, delivery_until = ?,
                revision = revision + 1 WHERE id = ? AND is_completed = 0
                AND message = ? AND remind_at = ? AND revision = ? AND remind_at <= ?
                AND (delivery_token IS NULL OR delivery_until <= ?)""",
                (token, (now + timedelta(seconds=lease_seconds)).isoformat(), reminder.id,
                 reminder.message, reminder.remind_at.astimezone(timezone.utc).isoformat(),
                 reminder.revision, now.isoformat(), now.isoformat())).rowcount
            return token if changed else None

    def renew_reminder_delivery(self, reminder_id: int, token: str, now: datetime,
                               lease_seconds: int = 300) -> bool:
        if now.tzinfo is None or now.utcoffset() is None or lease_seconds <= 0:
            raise ValueError("A timezone-aware clock and positive delivery lease are required.")
        with self.database.connect() as db:
            return db.execute("UPDATE reminders SET delivery_until = ? WHERE id = ? AND delivery_token = ?",
                ((now.astimezone(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(),
                 reminder_id, token)).rowcount > 0

    def defer_interrupted_reminder(self, reminder_id: int, token: str, now: datetime) -> bool:
        """Defer only the still-owned delivery; interrupted speech is not delivery."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Reminder clock must be timezone-aware.")
        due = now.astimezone(timezone.utc) + timedelta(seconds=60)
        with self.database.connect() as db:
            return db.execute("""UPDATE reminders SET remind_at = ?, is_completed = 0,
                delivery_token = NULL, delivery_until = NULL, revision = revision + 1
                WHERE id = ? AND delivery_token = ?""",
                (due.isoformat(), reminder_id, token)).rowcount > 0

    def finish_reminder_delivery(self, reminder_id: int, token: str, success: bool) -> bool:
        with self.database.connect() as db:
            return db.execute("""UPDATE reminders SET is_completed = ?, delivery_token = NULL,
                delivery_until = NULL, revision = revision + 1
                WHERE id = ? AND delivery_token = ?""",
                (int(success), reminder_id, token)).rowcount > 0

    
    def set_fact(self, key: str, value: str, connection=None) -> None:
        key = self._validate(key, "Fact key")
        value = self._validate(value, "Fact value")
        require_safe_storage(key + ": " + value)

        with self.database.connect() if connection is None else nullcontext(connection) as db:
            db.execute(
                """
                INSERT INTO facts (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def delete_fact(self, key: str, connection=None) -> bool:
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            return db.execute("DELETE FROM facts WHERE key = ?", (key,)).rowcount > 0

    def clear_facts(self, connection=None) -> int:
        with self.database.connect() if connection is None else nullcontext(connection) as db:
            return db.execute("DELETE FROM facts").rowcount

    def get_fact(self, key: str, *, recall_budget=False) -> str | None:
        with self.database.connect() as db:
            if recall_budget:
                db.execute("PRAGMA busy_timeout = 50")
            row = db.execute(
                "SELECT value FROM facts WHERE key = ?",
                (key,),
            ).fetchone()

            return row["value"] if row else None

    def list_facts(self) -> dict[str, str]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT key, value FROM facts ORDER BY key"
            ).fetchall()

            return {
                row["key"]: row["value"]
                for row in rows
            }
