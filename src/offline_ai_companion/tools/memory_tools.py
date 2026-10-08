
from datetime import datetime, timedelta, timezone

from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.router.query_router import Route


class MemoryTools:
    """Execute validated memory operations."""

    def __init__(self, repository: MemoryRepository):
        self.repository = repository

    def execute(self, route: Route) -> str:
        if route.intent == "set_name":
            self.repository.set_fact("user.name", route.content)
            return f"I'll call you {route.content}."

        if route.intent == "add_note":
            note = self.repository.add_note(route.content)
            return f"Saved your note: {note.content}"

        if route.intent == "list_notes":
            notes = self.repository.list_notes()
            if not notes:
                return "You have no saved notes."

            return "Your notes:\n" + "\n".join(
                f"{note.id}. {note.content}"
                for note in notes
            )

        if route.intent == "add_task":
            task = self.repository.add_task(route.content)
            return f"Added task: {task.title}"

        if route.intent == "list_tasks":
            tasks = self.repository.list_tasks(
                include_completed=False
            )
            if not tasks:
                return "You have no pending tasks."

            return "Your pending tasks:\n" + "\n".join(
                f"{task.id}. {task.title}"
                for task in tasks
            )

        if route.intent == "add_reminder":
            if route.minutes is None or route.minutes <= 0:
                raise ValueError(
                    "Reminder delay must be greater than zero."
                )

            remind_at = datetime.now(
                timezone.utc
            ) + timedelta(minutes=route.minutes)

            reminder = self.repository.add_reminder(
                route.content,
                remind_at,
            )

            return (
                f"Reminder saved: {reminder.message}. "
                f"I'll remind you in {route.minutes} minutes "
                "when reminder notifications are enabled."
            )

        if route.intent == "list_reminders":
            reminders = self.repository.list_reminders()
            if not reminders:
                return "You have no reminders."

            return "Your reminders:\n" + "\n".join(
                f"{reminder.id}. {reminder.message} — "
                f"{reminder.remind_at.astimezone().strftime('%Y-%m-%d %I:%M %p')}"
                f" ({'completed' if reminder.is_completed else 'pending'})"
                for reminder in reminders
            )

        raise ValueError(
            f"Unsupported memory intent: {route.intent}"
        )
