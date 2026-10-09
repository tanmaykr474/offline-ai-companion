
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationTurn:
    user: str
    assistant: str


class ConversationManager:
    """Manage bounded, in-memory conversation history."""

    def __init__(
        self,
        max_turns: int = 10,
        max_context_chars: int = 4000,
    ) -> None:
        if max_turns <= 0:
            raise ValueError(
                "Maximum conversation turns must be positive."
            )

        if max_context_chars <= 0:
            raise ValueError(
                "Maximum context characters must be positive."
            )

        self.max_turns = max_turns
        self.max_context_chars = max_context_chars

        self._history: deque[ConversationTurn] = deque(
            maxlen=max_turns
        )

    def add_turn(
        self,
        user: str,
        assistant: str,
    ) -> None:
        if not user or not user.strip():
            raise ValueError(
                "User message cannot be empty."
            )

        if not assistant or not assistant.strip():
            raise ValueError(
                "Assistant response cannot be empty."
            )

        self._history.append(
            ConversationTurn(
                user=user.strip(),
                assistant=assistant.strip(),
            )
        )

    def get_history(self) -> list[ConversationTurn]:
        return list(self._history)

    def build_context(self) -> str:
        """Return recent complete turns within the character budget."""

        selected = []
        used_chars = 0

        # Start with the newest conversation.
        for turn in reversed(self._history):
            formatted = (
                f"User: {turn.user}\n"
                f"Assistant: {turn.assistant}"
            )

            separator_length = 1 if selected else 0
            required = len(formatted) + separator_length

            if used_chars + required > self.max_context_chars:
                break

            selected.append(formatted)
            used_chars += required

        # Restore chronological order.
        return "\n".join(reversed(selected))

    def clear(self) -> None:
        self._history.clear()

    @property
    def turn_count(self) -> int:
        return len(self._history)
