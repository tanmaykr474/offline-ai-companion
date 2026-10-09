
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from offline_ai_companion.core.wake_detector import (
    WakeDetector,
)


@dataclass(frozen=True)
class ActivationDecision:
    """Action selected for a recognized transcript."""

    action: str
    text: str = ""


class ActivationController:
    """Route transcripts between passive and active modes."""

    PASSIVE = "passive"
    ACTIVE = "active"
    WAITING = "waiting"

    def __init__(
        self,
        wake_detector: WakeDetector | None = None,
        activation_timeout: float = 8.0,
    ) -> None:
        if activation_timeout <= 0:
            raise ValueError(
                "Activation timeout must be positive."
            )

        self.wake_detector = (
            wake_detector
            if wake_detector is not None
            else WakeDetector()
        )
        self.activation_timeout = activation_timeout
        self.active_until: datetime | None = None

    def route(
        self,
        transcript: str,
        now: datetime | None = None,
    ) -> ActivationDecision:
        """Decide what to do with one transcript."""

        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None:
            raise ValueError(
                "Current time must be timezone-aware."
            )

        transcript = transcript.strip()

        if not transcript:
            return ActivationDecision(
                action=self.PASSIVE,
            )

        detection = self.wake_detector.detect(
            transcript
        )

        # Explicit wake phrase always takes priority.
        if detection.activated:
            if detection.command:
                self.active_until = None

                return ActivationDecision(
                    action=self.ACTIVE,
                    text=detection.command,
                )

            # Wake phrase without a command:
            # allow one follow-up utterance.
            self.active_until = now + timedelta(
                seconds=self.activation_timeout
            )

            return ActivationDecision(
                action=self.WAITING,
            )

        # One follow-up utterance within the timeout.
        if self.active_until is not None:
            if now <= self.active_until:
                self.active_until = None

                return ActivationDecision(
                    action=self.ACTIVE,
                    text=transcript,
                )

            self.active_until = None

        return ActivationDecision(
            action=self.PASSIVE,
            text=transcript,
        )

    def reset(self) -> None:
        self.active_until = None
