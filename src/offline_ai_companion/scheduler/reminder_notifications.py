
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock

from offline_ai_companion.memory.models import Reminder
from offline_ai_companion.core.runtime_metrics import metrics


@dataclass(eq=False)
class ReminderNotification:
    reminder: Reminder
    finished: Event = field(default_factory=Event)
    error: Exception | None = None


class ReminderNotifications:
    """Coordinate reminder delivery with the main audio thread."""

    def __init__(self, max_pending: int = 10) -> None:
        if not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("Notification capacity must be positive.")
        self.max_pending = max_pending
        self.pending: Queue[ReminderNotification] = Queue(maxsize=max_pending)
        self.interrupt = Event()
        self.shutdown = Event()
        self._lock = Lock()
        self._active: set[ReminderNotification] = set()

    def request(self, reminder: Reminder) -> None:
        """Queue a reminder and wait for acknowledgment."""

        notification = ReminderNotification(reminder)

        with self._lock:
            if self.shutdown.is_set():
                raise RuntimeError(
                    "Notifications are shutting down."
                )

            if self.pending.qsize() + len(self._active) >= self.max_pending:
                metrics.count("notification_rejected")
                raise RuntimeError("Reminder notification capacity reached; delivery remains pending.")
            self.pending.put_nowait(notification)
            self.interrupt.set()

        while not notification.finished.wait(timeout=0.1):
            if self.shutdown.is_set():
                raise RuntimeError(
                    "Reminder delivery interrupted."
                )

        if notification.error is not None:
            raise notification.error

    def get_pending(self) -> ReminderNotification | None:
        """Retrieve and track the next notification."""

        with self._lock:
            if self.shutdown.is_set():
                return None

            try:
                notification = self.pending.get_nowait()
            except Empty:
                self.interrupt.clear()
                return None

            self._active.add(notification)
            return notification

    def acknowledge(
        self,
        notification: ReminderNotification,
        error: Exception | None = None,
    ) -> None:
        """Complete a notification and release its waiter."""

        with self._lock:
            if notification.finished.is_set():
                self._active.discard(notification)
                return

            if self.shutdown.is_set():
                notification.error = RuntimeError(
                    "Reminder delivery interrupted."
                )
            else:
                notification.error = error

            if notification in self._active:
                self.pending.task_done()
            self._active.discard(notification)
            notification.finished.set()

    def close(self) -> None:
        """Release queued and active notification waiters."""

        with self._lock:
            self.shutdown.set()
            self.interrupt.set()

            while True:
                try:
                    notification = self.pending.get_nowait()
                except Empty:
                    break

                notification.error = RuntimeError(
                    "Reminder delivery interrupted."
                )
                notification.finished.set()
                self.pending.task_done()

            for notification in self._active:
                notification.error = RuntimeError(
                    "Reminder delivery interrupted."
                )
                notification.finished.set()
                self.pending.task_done()

            self._active.clear()
