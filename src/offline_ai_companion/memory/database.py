
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from offline_ai_companion.config import DATABASE_PATH


class Database:
    """SQLite database connection and schema management."""

    def __init__(
        self,
        path: str | Path = DATABASE_PATH,
    ) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.path,
            timeout=10,
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        try:
            yield connection
            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def initialize(self) -> None:
        """Create database tables if they do not exist."""

        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    is_completed INTEGER NOT NULL DEFAULT 0
                        CHECK (is_completed IN (0, 1)),
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    is_completed INTEGER NOT NULL DEFAULT 0
                        CHECK (is_completed IN (0, 1)),
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_reminders_due
                    ON reminders(is_completed, remind_at);

                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );
            """)
