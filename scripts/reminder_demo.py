
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)
from offline_ai_companion.tts.piper import PiperTTS


def main():
    repository = MemoryRepository(Database())
    tts = PiperTTS()
    player = AudioPlayer()
    delivered = Event()

    def announce(reminder):
        print("[REMINDER] Delivering demo notification.")

        output = Path(
            "sample-data/audio/reminder_demo.wav"
        )

        tts.synthesize(
            f"Reminder: {reminder.message}",
            output,
        )

        player.play(output)
        delivered.set()

    repository.add_reminder(
        "This is a reminder scheduler test",
        datetime.now(timezone.utc)
        + timedelta(seconds=10),
    )

    scheduler = ReminderScheduler(
        repository=repository,
        on_reminder=announce,
        interval_seconds=0.5,
    )

    print("Reminder scheduled for 10 seconds from now.")
    scheduler.start()

    try:
        if not delivered.wait(timeout=30):
            print("Reminder did not play within 30 seconds.")
        else:
            print("Reminder successfully announced.")
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
