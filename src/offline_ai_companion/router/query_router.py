
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    intent: str
    content: str = ""
    minutes: int | None = None


class QueryRouter:
    """Classify supported commands without executing them."""

    NAME_QUESTIONS = {
        "what is my name",
        "what's my name",
        "whats my name",
        "what people call me",
        "what do people call me",
        "what does everyone call me",
        "what do you call me",
        "what am i called",
        "tell me my name",
        "tell me what my name is",
        "do you remember my name",
        "do you know my name",
        "can you tell me my name",
        "my name is what",
        "my name is",
        "who am i",
    }

    def route(self, query: str) -> Route:
        text = query.strip()

        if not text:
            raise ValueError("Query cannot be empty.")

        cleaned = text.rstrip(" .!?").strip()

        normalized = re.sub(
            r"\s+",
            " ",
            cleaned.lower(),
        )

        # 1. Name questions take precedence over updates.
        if normalized in self.NAME_QUESTIONS:
            return Route(intent="get_name")

        # 2. Clear name declarations update the fact store.
        name_match = re.fullmatch(
            r"(?:remember that\s+)?my name is\s+(.+)",
            cleaned,
            flags=re.IGNORECASE,
        )

        if name_match:
            name = name_match.group(1).strip()

            invalid_names = {
                "what",
                "who",
                "unknown",
                "someone",
            }

            if (
                name.lower() not in invalid_names
                and "?" not in text
            ):
                return Route(
                    intent="set_name",
                    content=name,
                )

        # 3. List commands.
        if normalized in {
            "show my notes",
            "list notes",
            "what are my notes",
        }:
            return Route("list_notes")

        if normalized in {
            "show my tasks",
            "list tasks",
            "show my pending tasks",
            "what are my tasks",
        }:
            return Route("list_tasks")

        if normalized in {
            "show my reminders",
            "list reminders",
        }:
            return Route("list_reminders")

        # 4. Reminder creation.
        reminder_match = re.fullmatch(
            r"remind me to (.+?) in (\d+) minutes?",
            cleaned,
            flags=re.IGNORECASE,
        )

        if reminder_match:
            return Route(
                intent="add_reminder",
                content=reminder_match.group(1).strip(),
                minutes=int(reminder_match.group(2)),
            )

        # 5. Save general notes.
        for prefix in (
            "remember that ",
            "remember ",
            "take a note ",
            "note that ",
        ):
            if normalized.startswith(prefix):
                content = cleaned[len(prefix):].strip()

                if content:
                    return Route(
                        intent="add_note",
                        content=content,
                    )

        # 6. Add tasks.
        for prefix in (
            "add a task to ",
            "add task to ",
            "create a task to ",
        ):
            if normalized.startswith(prefix):
                content = cleaned[len(prefix):].strip()

                if content:
                    return Route(
                        intent="add_task",
                        content=content,
                    )

        # 7. General questions go to the LLM.
        return Route(
            intent="chat",
            content=text,
        )
