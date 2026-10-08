
from datetime import datetime, timezone

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.models import Note, Task, Reminder


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

    def complete_task(self, task_id: int) -> bool:
        with self.database.connect() as db:
            result = db.execute(
                "UPDATE tasks SET is_completed = 1 WHERE id = ?",
                (task_id,),
            )
            return result.rowcount > 0

    def delete_task(self, task_id: int) -> bool:
        with self.database.connect() as db:
            result = db.execute(
                "DELETE FROM tasks WHERE id = ?",
                (task_id,),
            )
            return result.rowcount > 0

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
                UPDATE reminders SET is_completed = 1
                WHERE id = ?
                """,
                (reminder_id,),
            )
            return result.rowcount > 0

    def delete_reminder(self, reminder_id: int) -> bool:
        with self.database.connect() as db:
            result = db.execute(
                "DELETE FROM reminders WHERE id = ?",
                (reminder_id,),
            )
            return result.rowcount > 0

    
    def set_fact(self, key: str, value: str) -> None:
        key = self._validate(key, "Fact key")
        value = self._validate(value, "Fact value")

        with self.database.connect() as db:
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

    def get_fact(self, key: str) -> str | None:
        with self.database.connect() as db:
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
