
import re
from dataclasses import dataclass

from offline_ai_companion.config import (
    ASSISTANT_NAME,
    WAKE_PHRASES,
)


@dataclass(frozen=True)
class WakeDetectionResult:
    """Result of checking a transcript for a wake phrase."""

    activated: bool
    command: str = ""
    wake_phrase: str | None = None


class WakeDetector:
    """Detect configured wake phrases at the start of speech."""

    def __init__(
        self,
        assistant_name: str = ASSISTANT_NAME,
        wake_phrases: tuple[str, ...] = WAKE_PHRASES,
    ) -> None:
        self.assistant_name = assistant_name.strip()

        if not self.assistant_name:
            raise ValueError(
                "Assistant name cannot be empty."
            )

        phrases = {
            phrase.strip().lower()
            for phrase in wake_phrases
            if phrase.strip()
        }

        if not phrases:
            raise ValueError(
                "At least one wake phrase is required."
            )

        # Natural greetings address the assistant directly. Add aliases only
        # when its bare name is enabled, preserving custom wake-only setups.
        self._greeting_phrases = set()
        if self.assistant_name.casefold() in phrases:
            self._greeting_phrases = {
                f"hello {self.assistant_name.casefold()}",
                f"hi {self.assistant_name.casefold()}",
            }
            phrases.update(self._greeting_phrases)

        # Check longer phrases first.
        self.wake_phrases = tuple(
            sorted(
                phrases,
                key=len,
                reverse=True,
            )
        )

        self._patterns = [
            (
                phrase,
                re.compile(
                    r"^\s*"
                    + re.escape(phrase).replace(
                        r"\ ",
                        r"\s+",
                    )
                    + r"(?=$|[\s,!.?:;])"
                    + r"[\s,!.?:;]*",
                    flags=re.IGNORECASE,
                ),
            )
            for phrase in self.wake_phrases
        ]

    def detect(self, transcript: str) -> WakeDetectionResult:
        """Return activation status and command text."""

        if not transcript or not transcript.strip():
            return WakeDetectionResult(
                activated=False,
            )

        for phrase, pattern in self._patterns:
            match = pattern.match(transcript)

            if match is None:
                continue

            command = transcript[
                match.end():
            ].strip()
            if not command and phrase in self._greeting_phrases:
                command = "hello"

            return WakeDetectionResult(
                activated=True,
                command=command,
                wake_phrase=phrase,
            )

        return WakeDetectionResult(
            activated=False,
        )
