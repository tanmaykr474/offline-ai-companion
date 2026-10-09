
import sqlite3
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from offline_ai_companion.config import DATABASE_PATH
from offline_ai_companion.core.runtime_metrics import metrics


class Database:
    """SQLite database connection and schema management."""

    def __init__(
        self,
        path: str | Path = DATABASE_PATH,
        busy_timeout_seconds: float = 10,
    ) -> None:
        self.path = Path(path)
        if not math.isfinite(busy_timeout_seconds) or not 0 <= busy_timeout_seconds <= 60:
            raise ValueError("SQLite busy timeout must be between zero and 60 seconds.")
        self.busy_timeout_seconds = busy_timeout_seconds

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=self.busy_timeout_seconds)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()

        except BaseException as exc:
            if isinstance(exc, sqlite3.Error):
                metrics.count("sqlite_failures")
                if getattr(exc, "sqlite_errorcode", 0) & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    metrics.count("sqlite_busy_failures")
            if connection is not None:
                connection.rollback()
            raise

        finally:
            if connection is not None:
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

                CREATE TABLE IF NOT EXISTS passive_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL
                        CHECK (category IN ('event', 'task', 'preference', 'fact')),
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    event_time TEXT,
                    captured_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_passive_memories_category
                    ON passive_memories(category);

                CREATE INDEX IF NOT EXISTS idx_passive_memories_captured
                    ON passive_memories(captured_at);
            """)
            # Additive lifecycle migration; existing records and IDs are preserved.
            connection.execute("BEGIN IMMEDIATE")
            for table, columns in {
                "tasks": {"revision": "INTEGER NOT NULL DEFAULT 0"},
                "reminders": {"revision": "INTEGER NOT NULL DEFAULT 0",
                              "delivery_token": "TEXT", "delivery_until": "TEXT"},
            }.items():
                existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                for column, definition in columns.items():
                    if column not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
