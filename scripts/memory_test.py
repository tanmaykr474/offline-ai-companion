
from datetime import datetime, timedelta, timezone

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository


def main() -> None:
    repository = MemoryRepository(Database())

    print("\n--- NOTES ---")
    note = repository.add_note(
        "My AI companion stores memory locally."
    )
    print("Saved:", note)

    for item in repository.list_notes():
        print(item)

    print("\n--- TASKS ---")
    task = repository.add_task(
        "Complete AI companion hackathon"
    )
    print("Saved:", task)

    for item in repository.list_tasks():
        print(item)

    print("\n--- REMINDERS ---")
    remind_at = datetime.now(timezone.utc) + timedelta(
        minutes=10
    )

    reminder = repository.add_reminder(
        "Take a short break",
        remind_at,
    )
    print("Saved:", reminder)

    for item in repository.list_reminders():
        print(item)

    print("\nMemory test completed.")


if __name__ == "__main__":
    main()
