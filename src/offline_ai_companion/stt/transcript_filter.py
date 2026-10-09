
import re


def is_invalid_transcript(text: str) -> bool:
    """Return True for empty or non-speech transcripts."""

    if not text or not text.strip():
        return True

    cleaned = text.strip()

    # Remove known Whisper non-speech markers.
    cleaned = re.sub(
        r"\[(?:inaudible|silence|music|noise)\]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Ignore punctuation-only results.
    cleaned = re.sub(
        r"[\W_]+",
        "",
        cleaned,
    )

    return not cleaned
