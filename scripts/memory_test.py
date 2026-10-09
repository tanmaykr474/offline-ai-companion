from offline_ai_companion.core.privacy_policy import debug_text

from datetime import datetime, timedelta, timezone

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository


def main() -> None:
    repository = MemoryRepository(Database())

    print("\n--- NOTES ---")
    note = repository.add_note(
        "My AI companion stores memory locally."
    )
    print("Saved:", debug_text(str(note)))

    for item in repository.list_notes():
        print(debug_text(str(item)))

    print("\n--- TASKS ---")
    task = repository.add_task(
        "Complete AI companion hackathon"
    )
    print("Saved:", debug_text(str(task)))

    for item in repository.list_tasks():
        print(debug_text(str(item)))

    print("\n--- REMINDERS ---")
    remind_at = datetime.now(timezone.utc) + timedelta(
        minutes=10
    )

    reminder = repository.add_reminder(
        "Take a short break",
        remind_at,
    )
    print("Saved:", debug_text(str(reminder)))

    for item in repository.list_reminders():
        print(debug_text(str(item)))

    print("\nMemory test completed.")


if __name__ == "__main__":
    main()
