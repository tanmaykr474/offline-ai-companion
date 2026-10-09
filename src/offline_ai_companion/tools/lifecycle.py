"""Deterministic task/reminder commands with optimistic SQLite confirmations."""
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from offline_ai_companion.core.privacy_policy import contains_secret, STORAGE_REFUSAL
from offline_ai_companion.scheduler.reminder_time import parse_reminder_time


def clean_command(text):
    return re.sub(r"^(?:hey\s+)?nova\b[\s,:]*", "", text.strip(), flags=re.I).strip().rstrip(".!?")


@dataclass(frozen=True)
class LifecycleCommand:
    kind: str
    action: str
    target: str = ""
    value: str = ""


def _target_kind(target):
    """Prefer the grammatical record type over words inside its title."""
    match = re.match(r"^(?:my )?(task|reminder)(?:\b|:)", target, re.I)
    if match:
        return match[1].lower()
    match = re.search(r"\b(task|reminder)$", target, re.I)
    return match[1].lower() if match else None


def parse_lifecycle_command(text: str) -> LifecycleCommand | None:
    text = clean_command(text)
    low = text.lower()
    for kind, names in {
        "task": {"show my tasks", "list tasks", "show my pending tasks", "what are my tasks"},
        "reminder": {"show my reminders", "list reminders", "show my upcoming reminders"},
    }.items():
        match = re.fullmatch(r"(.+?)(?: page (\d+))?", low)
        if match and match[1] in names:
            return LifecycleCommand(kind, "list", value=match[2] or "1")
    match = re.fullmatch(r"(?:add|create) (?:a )?task to (.+)", text, re.I)
    if match:
        return LifecycleCommand("task", "add", value=match[1])
    match = re.fullmatch(r"rename (.+?) to (.+)", text, re.I)
    if match and _target_kind(match[1]) == "task":
        return LifecycleCommand("task", "rename", match[1], match[2])
    match = re.fullmatch(r"(?:mark (.+?) as completed|complete (.+))", text, re.I)
    if match:
        target = match[1] or match[2]
        if _target_kind(target) == "task":
            return LifecycleCommand("task", "complete", target)
    match = re.fullmatch(r"(?:delete|remove|cancel) (.+)", text, re.I)
    if match:
        target = match[1]
        if _target_kind(target) == "task":
            return LifecycleCommand("task", "delete", target)
        if _target_kind(target) == "reminder":
            return LifecycleCommand("reminder", "cancel" if low.startswith("cancel ") else "delete", target)
    match = re.fullmatch(r"snooze (.+?) for (\d+) (minutes?|hours?)", text, re.I)
    if match:
        return LifecycleCommand("reminder", "snooze", match[1], f"in {match[2]} {match[3]}")
    match = re.fullmatch(r"reschedule (.+?) to (.+)", text, re.I)
    if match:
        return LifecycleCommand("reminder", "reschedule", match[1], match[2])
    if low.startswith("remind me"):
        body = text[len("remind me"):].strip()
        match = re.fullmatch(r"(?:to|about) (.+?) ((?:in \d+ (?:minutes?|hours?)|(?:today |tomorrow |on .+? )?at .+))", body, re.I)
        if match:
            return LifecycleCommand("reminder", "add", match[1], match[2])
        return LifecycleCommand("reminder", "invalid")
    return None


@dataclass(frozen=True)
class PendingLifecycle:
    command: LifecycleCommand
    record_id: int
    snapshot: tuple
    deadline: datetime
    when: datetime | None = None


class LifecycleManagement:
    PAGE_SIZE = 3

    def __init__(self, tools, confirmation, memory_management, clock=None, timeout_seconds=120):
        if timeout_seconds <= 0:
            raise ValueError("Confirmation timeout must be positive.")
        self.repository = tools.repository
        self.zone = tools.reminder_zone
        self.clock = clock or tools.clock
        self.confirmation = confirmation
        self.memory_management = memory_management
        self.timeout_seconds = timeout_seconds
        self.pending = None

    def clear(self):
        self.pending = None

    def _now(self):
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The lifecycle clock must include a timezone.")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _table(kind):
        return "tasks" if kind == "task" else "reminders"

    def _rows(self, kind):
        table = self._table(kind)
        with self.repository.database.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]

    @staticmethod
    def _private(row, kind):
        return contains_secret(row["title" if kind == "task" else "message"])

    def _resolve(self, command):
        rows = self._rows(command.kind)
        target = command.target.strip().lower()
        explicit = re.fullmatch(rf"(?:{command.kind}:|(?:my )?{command.kind} (?:number )?)(\d+)", target)
        if explicit:
            matches = [row for row in rows if row["id"] == int(explicit[1])]
        else:
            label = re.sub(r"\b(?:my|task|reminder|to)\b", " ", target)
            words = set(re.findall(r"\w+", label))
            field = "title" if command.kind == "task" else "message"
            exact = [row for row in rows if words and row[field].lower() == label.strip()]
            matches = exact or [row for row in rows if words and words <= set(re.findall(r"\w+", row[field].lower()))]
            if not words and target in {f"my {command.kind}", command.kind}:
                matches = rows
        if not matches:
            return None, f"No matching {command.kind} was found. Nothing changed."
        if len(matches) != 1:
            ids = ", ".join(f"{command.kind}:{row['id']}" for row in matches[:5])
            return None, f"Multiple {command.kind}s match: {ids}. Specify a number; nothing changed."
        return matches[0], None

    def _list(self, command):
        rows = [row for row in self._rows(command.kind) if not row["is_completed"] and not self._private(row, command.kind)]
        if command.kind == "reminder":
            rows.sort(key=lambda row: (row["remind_at"], row["id"]))
        if len(command.value) > 6:
            return "Choose a page number from 1 to 999999."
        page = int(command.value)
        if page < 1:
            return "Choose page 1 or greater."
        selected = rows[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]
        if not selected:
            return f"No pending {command.kind}s on this page."
        lines = []
        for row in selected:
            title = row["title" if command.kind == "task" else "message"]
            line = f"{command.kind}:{row['id']}: {title[:180]}"
            if command.kind == "reminder":
                when = datetime.fromisoformat(row["remind_at"])
                label = "due" if when <= self._now() else "upcoming"
                line += f" — {when.astimezone(self.zone).strftime('%Y-%m-%d %I:%M %p %Z')} ({label})"
            lines.append(line)
        if page * self.PAGE_SIZE < len(rows):
            lines.append(f"Say Show my {'pending tasks' if command.kind == 'task' else 'upcoming reminders'} page {page + 1}.")
        return f"Your pending {command.kind}s:\n" + "\n".join(lines)

    def _apply(self, pending):
        command = pending.command
        table = self._table(command.kind)
        try:
            with self.repository.database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if self._now() >= pending.deadline:
                    return "That confirmation expired. Nothing changed."
                row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (pending.record_id,)).fetchone()
                if row is None or tuple(row) != pending.snapshot:
                    return "The reviewed record changed. Please repeat the command; nothing changed."
                if command.kind == "reminder" and row["delivery_token"] is not None:
                    return "Reminder delivery is in progress. Try again after it finishes; nothing changed."
                if pending.when is not None and pending.when <= self._now():
                    return "The proposed reminder time is now past or due. Choose a future time; nothing changed."
                args = (pending.record_id,)
                action = command.action
                if command.kind == "task":
                    operation = {"delete": self.repository.delete_task, "complete": self.repository.complete_task,
                                 "rename": self.repository.rename_task}[action]
                    if action == "rename":
                        args += (command.value,)
                else:
                    operation = {"delete": self.repository.delete_reminder, "cancel": self.repository.cancel_reminder,
                                 "snooze": self.repository.reschedule_reminder,
                                 "reschedule": self.repository.reschedule_reminder}[action]
                    if action in {"snooze", "reschedule"}:
                        args += (pending.when,)
                if not operation(*args, connection=db):
                    raise RuntimeError("Lifecycle change failed")
        except (sqlite3.Error, ValueError, RuntimeError, OSError):
            return "The change could not be saved. Nothing changed; please try again."
        verb = {"complete": "completed", "delete": "deleted", "rename": "renamed",
                "cancel": "cancelled", "snooze": "snoozed", "reschedule": "rescheduled"}[command.action]
        return f"Saved: {command.kind}:{pending.record_id} {verb}."

    def handle(self, text):
        normalized = clean_command(text).lower()
        command = parse_lifecycle_command(text)
        previous = self.pending
        self.clear()
        if contains_secret(text):
            self.confirmation.clear()
            if self.memory_management:
                self.memory_management.clear()
            return STORAGE_REFUSAL
        if previous is not None:
            if normalized in {"no", "cancel", "no cancel"}:
                return "Cancelled. Nothing changed."
            accepted = {"yes", "confirm", f"yes {previous.command.action}"}
            if normalized in accepted:
                return self._apply(previous)
            if normalized.startswith(("yes", "confirm")):
                return "That was not an unambiguous confirmation. Nothing changed."
            # Any other request discards the prior operation and routes normally.
        if command is None:
            return None
        self.confirmation.clear()
        if self.memory_management:
            self.memory_management.clear()
        if command.action == "invalid":
            return "Please specify what to remind you about and a future time, such as Remind me to call Mom tomorrow at 6 PM."
        if command.action == "list":
            return self._list(command)
        if command.action == "add":
            if command.kind == "task":
                task = self.repository.add_task(command.value)
                return f"Added task:{task.id}: {task.title[:180]}"
            try:
                when = parse_reminder_time(command.value, self._now(), self.zone)
            except ValueError as exc:
                return str(exc)
            reminder = self.repository.add_reminder(command.target, when)
            return (f"Reminder saved: reminder:{reminder.id}: {reminder.message[:180]}. "
                    f"At {when.astimezone(self.zone).strftime('%Y-%m-%d %I:%M %p %Z')} "
                    "when reminder notifications are enabled.")
        row, error = self._resolve(command)
        if error:
            return error
        if command.kind == "task" and command.action == "complete" and row["is_completed"]:
            return f"task:{row['id']} is already completed. Nothing changed."
        if command.kind == "reminder":
            if row["delivery_token"] is not None:
                return "Reminder delivery is in progress or awaiting recovery. Try again after it finishes; nothing changed."
            if command.action == "cancel" and row["is_completed"]:
                return f"reminder:{row['id']} is already inactive. Nothing changed."
        when = None
        if command.action in {"snooze", "reschedule"}:
            try:
                when = parse_reminder_time(command.value, self._now(), self.zone)
            except ValueError as exc:
                return str(exc)
        self.pending = PendingLifecycle(command, row["id"], tuple(row.values()),
                                        self._now() + timedelta(seconds=self.timeout_seconds), when)
        title = "[private content hidden]" if self._private(row, command.kind) else row[
            "title" if command.kind == "task" else "message"][:180]
        details = f" to {command.value[:180]}" if command.action == "rename" else ""
        if when:
            details = f" to {when.astimezone(self.zone).strftime('%Y-%m-%d %I:%M %p %Z')}"
        return f"Confirm {command.action} {command.kind}:{row['id']} ({title}){details}? Reply Yes or No."
