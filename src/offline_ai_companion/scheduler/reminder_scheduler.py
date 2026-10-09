
import logging
from datetime import datetime, timezone
from threading import Event, Lock, Thread, current_thread
from typing import Callable

from offline_ai_companion.memory.models import Reminder
from offline_ai_companion.memory.repository import MemoryRepository


logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Poll SQLite and deliver due reminders in the background."""

    def __init__(
        self,
        repository: MemoryRepository,
        on_reminder: Callable[[Reminder], None],
        interval_seconds: float = 1.0,
        clock: Callable[[], datetime] | None = None,
        completion_retries: int = 3,
        completion_retry_delay: float = 0.5,
    ):
        if interval_seconds <= 0:
            raise ValueError("Polling interval must be positive.")

        if completion_retries < 1:
            raise ValueError(
                "Completion retries must be at least 1."
            )

        if completion_retry_delay < 0:
            raise ValueError(
                "Completion retry delay cannot be negative."
            )

        self.repository = repository
        self.on_reminder = on_reminder
        self.interval_seconds = interval_seconds
        self.clock = clock or (
            lambda: datetime.now(timezone.utc)
        )

        self.completion_retries = completion_retries
        self.completion_retry_delay = completion_retry_delay

        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()
        self._poll_lock = Lock()

    def _complete_with_retry(self, reminder_id: int) -> bool:
        """Retry transient database completion failures."""

        for attempt in range(self.completion_retries):
            try:
                return bool(
                    self.repository.complete_reminder(reminder_id)
                )

            except Exception:
                logger.exception(
                    "Reminder %s completion failed "
                    "(attempt %s/%s).",
                    reminder_id,
                    attempt + 1,
                    self.completion_retries,
                )

                if attempt == self.completion_retries - 1:
                    return False

                if self._stop_event.wait(
                    self.completion_retry_delay
                ):
                    return False

        return False

    def check_due(self) -> int:
        """Deliver due reminders and mark successful deliveries."""

        with self._poll_lock:
            reminders = self.repository.get_due_reminders(
                self.clock()
            )

            delivered = 0

            for reminder in reminders:
                if self._stop_event.is_set():
                    break

                try:
                    self.on_reminder(reminder)

                except Exception:
                    logger.exception(
                        "Failed to deliver reminder %s",
                        reminder.id,
                    )
                    continue

                if self._complete_with_retry(reminder.id):
                    delivered += 1
                else:
                    logger.error(
                        "Reminder %s was announced but "
                        "could not be marked completed. "
                        "It may be delivered again.",
                        reminder.id,
                    )

            return delivered

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_due()

            except Exception:
                logger.exception(
                    "Reminder scheduler polling failed."
                )

            self._stop_event.wait(
                self.interval_seconds
            )

    def start(self) -> None:
        """Start the scheduler if it is not already running."""

        with self._lifecycle_lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                return

            self._stop_event.clear()

            self._thread = Thread(
                target=self._run,
                name="reminder-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """Request shutdown and report whether it completed."""

        if timeout < 0:
            raise ValueError(
                "Shutdown timeout cannot be negative."
            )

        self._stop_event.set()

        with self._lifecycle_lock:
            thread = self._thread

        if thread is None:
            return True

        if thread is current_thread():
            return False

        if thread.is_alive():
            thread.join(timeout=timeout)

        if thread.is_alive():
            logger.warning(
                "Reminder scheduler did not stop "
                "within %.2f seconds.",
                timeout,
            )
            return False

        return True

    @property
    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return (
                self._thread is not None
                and self._thread.is_alive()
            )
