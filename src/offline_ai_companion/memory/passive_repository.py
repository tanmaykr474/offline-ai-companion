
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from contextlib import nullcontext

from offline_ai_companion.memory.database import Database
from offline_ai_companion.config import PASSIVE_MEMORY_RETENTION_DAYS
from offline_ai_companion.core.privacy_policy import allows_storage


@dataclass(frozen=True)
class PassiveMemory:
    id: int
    category: str
    subject: str
    content: str
    evidence: str
    event_time: str | None
    captured_at: str


class PassiveMemoryRepository:
    """Store and retrieve structured passive memories."""

    def __init__(self, database: Database, retention_days: int = PASSIVE_MEMORY_RETENTION_DAYS,
                 clock=None):
        if retention_days < 0:
            raise ValueError("Retention days cannot be negative.")
        self.database = database
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.database.initialize()

    def _cutoff(self, now=None):
        now = now or self.clock()
        if now.utcoffset() is None:
            raise ValueError("Retention clock must be timezone-aware.")
        return (now.astimezone(timezone.utc) - timedelta(days=self.retention_days)).isoformat()

    def purge_expired(self, now=None) -> int:
        """Explicit lifecycle operation; normal reads never delete rows."""
        if self.retention_days == 0:
            return 0
        with self.database.connect() as connection:
            result = connection.execute(
                "DELETE FROM passive_memories WHERE julianday(captured_at) <= julianday(?)",
                (self._cutoff(now),),
            )
            return result.rowcount

    @staticmethod
    def _fingerprint(
        category: str,
        subject: str,
        content: str,
        event_time: str | None,
    ) -> str:
        normalized = "|".join(
            [
                category.lower().strip(),
                subject.lower().strip(),
                re.sub(
                    r"\s+",
                    " ",
                    content.lower().strip(),
                ),
                event_time or "",
            ]
        )

        return hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

    def add(
        self,
        category: str,
        subject: str,
        content: str,
        evidence: str,
        event_time: str | None = None,
        captured_at: datetime | None = None,
    ) -> bool:
        """Return True when a new memory is stored."""

        if category not in {
            "event",
            "task",
            "preference",
            "fact",
        }:
            raise ValueError("Unsupported memory category.")

        if not all(
            isinstance(value, str) and value.strip()
            for value in (subject, content, evidence)
        ):
            raise ValueError("Memory fields cannot be empty.")
        if not allows_storage(subject + " " + content + " " + evidence):
            raise ValueError("Sensitive speech cannot be stored automatically.")

        if event_time is not None:
            datetime.fromisoformat(event_time)

        timestamp = captured_at or datetime.now(
            timezone.utc
        )

        if timestamp.tzinfo is None:
            raise ValueError(
                "Capture timestamp must be timezone-aware."
            )

        fingerprint = self._fingerprint(
            category,
            subject,
            content,
            event_time,
        )

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO passive_memories (
                    category,
                    subject,
                    content,
                    evidence,
                    event_time,
                    captured_at,
                    fingerprint
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category,
                    subject.strip(),
                    content.strip(),
                    evidence.strip(),
                    event_time,
                    timestamp.astimezone(
                        timezone.utc
                    ).isoformat(),
                    fingerprint,
                ),
            )

            return cursor.rowcount == 1

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> list[PassiveMemory]:
        if limit < 1:
            raise ValueError("Limit must be positive.")
        if offset < 0:
            raise ValueError("Offset cannot be negative.")

        query = """
            SELECT
                id, category, subject, content,
                evidence, event_time, captured_at
            FROM passive_memories
        """

        parameters = []

        conditions = []
        if category is not None:
            conditions.append("category = ?")
            parameters.append(category)

        if self.retention_days and not include_expired:
            conditions.append("julianday(captured_at) > julianday(?)")
            parameters.append(self._cutoff(now))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))

        with self.database.connect() as connection:
            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return [
            PassiveMemory(
                id=row["id"],
                category=row["category"],
                subject=row["subject"],
                content=row["content"],
                evidence=row["evidence"],
                event_time=row["event_time"],
                captured_at=row["captured_at"],
            )
            for row in rows
        ]

    def get(self, memory_id: int, include_expired: bool = False, *, recall_budget=False) -> PassiveMemory | None:
        query = "SELECT id, category, subject, content, evidence, event_time, captured_at FROM passive_memories WHERE id = ?"
        parameters = [memory_id]
        if self.retention_days and not include_expired:
            query += " AND julianday(captured_at) > julianday(?)"
            parameters.append(self._cutoff())
        with self.database.connect() as connection:
            if recall_budget:
                connection.execute("PRAGMA busy_timeout = 50")
            row = connection.execute(query, parameters).fetchone()
        return PassiveMemory(**dict(row)) if row is not None else None

    def recall_candidates(self, prefixes=(), terms=(), limit=33, budget_seconds=0.2, category=None):
        """Bounded, read-only recall query. Retention and attribution apply in SQL.

        Prefixes select known relations; terms select historical event evidence.
        A progress handler and short lock wait bound SQLite work, not just output.
        No transcript or memory data is logged.
        """
        if not 1 <= limit <= 65 or not 0 < budget_seconds <= 1:
            raise ValueError("Invalid recall query budget.")
        if len(prefixes) > 16 or len(terms) > 16:
            raise ValueError("Too many recall terms.")
        clauses, parameters = ["lower(trim(subject)) = 'speaker'",
                               "length(content) BETWEEN 1 AND 300",
                               "length(evidence) BETWEEN 1 AND 1500"], []
        if category is not None:
            if category not in {"event", "task", "preference", "fact"}:
                raise ValueError("Unsupported recall category.")
            clauses.append("category = ?")
            parameters.append(category)
        matches = []
        for prefix in prefixes:
            if not re.fullmatch(r"[a-z _-]{1,100}", prefix):
                raise ValueError("Invalid recall prefix.")
            matches.append("lower(content) LIKE ?")
            parameters.append(prefix.replace("_", "\\_") + "%")
            matches[-1] += " ESCAPE '\\'"
        for term in terms:
            if not re.fullmatch(r"[a-z]{2,40}", term):
                raise ValueError("Invalid recall term.")
            matches.append("(category = 'event' AND lower(evidence) LIKE ?)")
            parameters.append("%" + term + "%")
        if matches:
            clauses.append("(" + " OR ".join(matches) + ")")
        if self.retention_days:
            clauses.append("julianday(captured_at) > julianday(?)")
            parameters.append(self._cutoff())
        deadline = time.monotonic() + budget_seconds
        with self.database.connect() as connection:
            connection.execute("PRAGMA busy_timeout = 50")
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            rows = connection.execute(
                "SELECT id, category, subject, content, evidence, event_time, captured_at "
                "FROM passive_memories WHERE " + " AND ".join(clauses) + " ORDER BY id DESC LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        return [PassiveMemory(**dict(row)) for row in rows]

    def delete(self, memory_id: int, connection=None) -> bool:
        with self.database.connect() if connection is None else nullcontext(connection) as connection:
            cursor = connection.execute(
                "DELETE FROM passive_memories WHERE id = ?",
                (memory_id,),
            )
            return cursor.rowcount == 1

    def clear(self, connection=None) -> int:
        """Delete all captured passive memories."""

        with self.database.connect() if connection is None else nullcontext(connection) as connection:
            cursor = connection.execute(
                "DELETE FROM passive_memories"
            )
            return cursor.rowcount
