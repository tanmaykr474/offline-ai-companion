
import logging
from threading import Event

logger = logging.getLogger(__name__)


class AudioRecovery:
    """Handle recoverable audio failures."""

    def __init__(
        self,
        retry_delay: float = 2.0,
    ) -> None:
        if retry_delay < 0:
            raise ValueError(
                "Retry delay cannot be negative."
            )

        self.retry_delay = retry_delay

    def handle_failure(
        self,
        component: str,
        error: Exception,
        stop_event: Event,
    ) -> None:
        """Log a failure and wait before retrying."""

        logger.error(
            "%s failed: %s",
            component,
            error,
        )

        print(
            f"[AUDIO ERROR] {component}: {error}"
        )

        if not stop_event.is_set():
            stop_event.wait(self.retry_delay)
