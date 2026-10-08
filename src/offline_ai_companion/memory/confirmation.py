
from dataclasses import dataclass

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

    def __init__(self) -> None:
        self.pending: FactProposal | None = None

    def propose(self, proposal: FactProposal) -> None:
        self.pending = proposal

    def clear(self) -> None:
        self.pending = None

    def resolve(self, message: str) -> ConfirmationResult:
        if self.pending is None:
            return ConfirmationResult("none")

        normalized = message.lower().strip().rstrip(" .!?")

        if normalized in self.YES:
            proposal = self.pending
            self.clear()
            return ConfirmationResult("confirmed", proposal)

        if normalized in self.NO:
            self.clear()
            return ConfirmationResult("rejected")

        return ConfirmationResult("unrecognized")
