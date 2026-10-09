
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from offline_ai_companion.memory.intelligent_extractor import (
    FactProposal,
)


@dataclass(frozen=True)
class ConfirmationResult:
    status: str
    proposal: FactProposal | None = None


class FactConfirmationManager:
    """Track one proposed fact until the user accepts or rejects it."""

    YES = {
        "yes", "yeah", "yep", "correct",
        "confirm", "save it", "yes save it",
        "go ahead", "that's right",
    }

    NO = {
        "no", "nope", "cancel", "reject",
        "don't save", "do not save",
        "forget it", "that's wrong",
    }

    def __init__(self, timeout_seconds: int = 120, clock=None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Confirmation timeout must be positive.")
        self.timeout_seconds = timeout_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.deadline = None
        self.pending: FactProposal | None = None

    def propose(self, proposal: FactProposal) -> None:
        now = self._now()
        self.pending = proposal
        self.deadline = now + timedelta(seconds=self.timeout_seconds)

    def _now(self):
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("Confirmation clock must be timezone-aware.")
        return now

    def clear(self) -> None:
        self.pending = None
        self.deadline = None

    def resolve(self, message: str) -> ConfirmationResult:
        if self.pending is None:
            return ConfirmationResult("none")
        if self.deadline is not None and self._now() >= self.deadline:
            self.clear()
            return ConfirmationResult("expired")

        normalized = message.lower().strip().rstrip(" .!?")

        if normalized in self.YES:
            proposal = self.pending
            self.clear()
            return ConfirmationResult("confirmed", proposal)

        if normalized in self.NO:
            self.clear()
            return ConfirmationResult("rejected")

        return ConfirmationResult("unrecognized")
