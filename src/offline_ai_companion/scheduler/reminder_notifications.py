
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock

from offline_ai_companion.memory.models import Reminder


@dataclass(eq=False)
class ReminderNotification:
    reminder: Reminder
    finished: Event = field(default_factory=Event)
    error: Exception | None = None


class ReminderNotifications:
    """Coordinate reminder delivery with the main audio thread."""

    def __init__(self) -> None:
        self.pending: Queue[ReminderNotification] = Queue()
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

            for notification in self._active:
                notification.error = RuntimeError(
                    "Reminder delivery interrupted."
                )
                notification.finished.set()

            self._active.clear()
