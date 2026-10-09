
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from offline_ai_companion.config import CONVERSATION_RETENTION_SECONDS
from offline_ai_companion.core.privacy_policy import history_text


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
        retention_seconds: int = CONVERSATION_RETENTION_SECONDS,
        clock=None,
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
        if retention_seconds < 0:
            raise ValueError("Conversation retention cannot be negative.")
        self.retention_seconds = retention_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._timestamps = deque(maxlen=max_turns)

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

        self.expire()
        timestamp = self.clock()
        if timestamp.utcoffset() is None:
            raise ValueError("Conversation clock must be timezone-aware.")
        self._timestamps.append(timestamp)
        self._history.append(
            ConversationTurn(
                user=history_text(user.strip()),
                assistant=history_text(assistant.strip()),
            )
        )

    def get_history(self) -> list[ConversationTurn]:
        self.expire()
        return list(self._history)

    def expire(self, now=None) -> int:
        if not self.retention_seconds:
            return 0
        now = now or self.clock()
        if now.utcoffset() is None:
            raise ValueError("Conversation clock must be timezone-aware.")
        cutoff = now - timedelta(seconds=self.retention_seconds)
        retained = [(turn, stamp) for turn, stamp in zip(self._history, self._timestamps)
                    if stamp > cutoff]
        removed = len(self._history) - len(retained)
        self._history.clear()
        self._timestamps.clear()
        for turn, stamp in retained:
            self._history.append(turn)
            self._timestamps.append(stamp)
        return removed

    def build_context(self) -> str:
        """Return recent complete turns within the character budget."""

        selected = []
        used_chars = 0

        # Start with the newest conversation.
        for turn in reversed(self.get_history()):
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
        self._timestamps.clear()

    @property
    def turn_count(self) -> int:
        return len(self.get_history())
