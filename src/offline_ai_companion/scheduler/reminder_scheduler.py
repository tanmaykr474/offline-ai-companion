
import logging
import time
from offline_ai_companion.core.runtime_metrics import metrics
from datetime import datetime, timezone
from threading import Event, Lock, Thread, current_thread
from typing import Callable

from offline_ai_companion.memory.models import Reminder
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.core.cancellation import ResponseInterrupted


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
        delivery_lease_seconds: int = 300,
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

        if delivery_lease_seconds <= 0:
            raise ValueError("Delivery lease must be positive.")

        self.repository = repository
        self.on_reminder = on_reminder
        self.interval_seconds = interval_seconds
        self.clock = clock or (
            lambda: datetime.now(timezone.utc)
        )

        self.completion_retries = completion_retries
        self.completion_retry_delay = completion_retry_delay
        self.delivery_lease_seconds = delivery_lease_seconds

        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()
        self._poll_lock = Lock()

    def _complete_with_retry(self, reminder_id: int, token: str | None = None) -> bool:
        """Retry transient database completion failures."""

        for attempt in range(self.completion_retries):
            try:
                return bool(
                    self.repository.complete_reminder(reminder_id) if token is None
                    else self.repository.finish_reminder_delivery(reminder_id, token, True)
                )

            except Exception as exc:
                logger.error(
                    "Reminder %s completion failed "
                    "(attempt %s/%s): %s",
                    reminder_id,
                    attempt + 1,
                    self.completion_retries,
                    type(exc).__name__,
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

                token = None
                heartbeat_stop = Event()
                heartbeat = None
                if isinstance(self.repository, MemoryRepository):
                    token = self.repository.claim_reminder(reminder, self.clock(), self.delivery_lease_seconds)
                    if token is None:
                        continue

                    def renew(reminder_id=reminder.id, claim=token, stop=heartbeat_stop):
                        while not stop.wait(self.delivery_lease_seconds / 3):
                            try:
                                if not self.repository.renew_reminder_delivery(
                                    reminder_id, claim, self.clock(), self.delivery_lease_seconds
                                ):
                                    break
                            except Exception as exc:
                                logger.error("Reminder lease renewal failed: %s", type(exc).__name__)
                    heartbeat = Thread(target=renew, name="reminder-lease", daemon=True)
                    heartbeat.start()

                try:
                    started = time.monotonic()
                    if metrics.enabled:
                        try:
                            due = getattr(reminder, "remind_at", None)
                            if isinstance(due, datetime) and due.utcoffset() is not None:
                                now = self.clock()
                                if isinstance(now, datetime) and now.utcoffset() is not None:
                                    metrics.observe("reminder_lateness", max(0., (now - due).total_seconds()))
                        except Exception:
                            # Optional instrumentation must not change delivery.
                            metrics.count("resource_sample_failures")
                    self.on_reminder(reminder)

                except Exception as exc:
                    metrics.observe("reminder_delivery", time.monotonic() - started, "error")
                    metrics.count("reminder_delivery_failures")
                    logger.error(
                        "Failed to deliver reminder %s: %s",
                        reminder.id, type(exc).__name__,
                    )
                    heartbeat_stop.set()
                    if heartbeat is not None:
                        heartbeat.join(timeout=1)
                    if token is not None:
                        try:
                            if isinstance(exc, ResponseInterrupted):
                                self.repository.defer_interrupted_reminder(reminder.id, token, self.clock())
                            else:
                                self.repository.finish_reminder_delivery(reminder.id, token, False)
                        except Exception as release_error:
                            logger.error("Reminder claim release failed: %s", type(release_error).__name__)
                    continue

                except BaseException:
                    metrics.observe("reminder_delivery", time.monotonic() - started, "interrupted")
                    # Direct check_due callers may interrupt delivery too.
                    heartbeat_stop.set()
                    if heartbeat is not None:
                        heartbeat.join(timeout=1)
                    if token is not None:
                        try:
                            self.repository.finish_reminder_delivery(reminder.id, token, False)
                        except Exception as release_error:
                            logger.error("Reminder claim release failed: %s", type(release_error).__name__)
                    raise

                try:
                    metrics.observe("reminder_delivery", time.monotonic() - started)
                    completed = self._complete_with_retry(reminder.id, token)
                finally:
                    heartbeat_stop.set()
                    if heartbeat is not None:
                        heartbeat.join(timeout=1)
                if completed:
                    metrics.count("reminder_completed")
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

            except Exception as exc:
                metrics.count("scheduler_failures")
                logger.error(
                    "Reminder scheduler polling failed: %s", type(exc).__name__
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
