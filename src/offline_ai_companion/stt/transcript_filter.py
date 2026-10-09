
import re


def strip_audio_captions(text: str) -> str:
    """Remove Whisper captions while retaining adjacent spoken words.

    Square brackets denote STT annotations. Parentheses are removed only
    for recognized audio cues, so ordinary parenthetical speech survives.
    """
    if not isinstance(text, str):
        return ""
    return re.sub(
        r"\[[^\]]*\]|\((?:dramatic music|music|applause|silence|"
        r"background noise|blank_audio|no speech|noise|inaudible|"
        r"xbox sound)\)",
        " ", text, flags=re.IGNORECASE,
    ).strip()


def is_invalid_transcript(text: str) -> bool:
    """Return True for empty or non-speech transcripts."""

    cleaned = strip_audio_captions(text)

    # Ignore punctuation-only results.
    cleaned = re.sub(
        r"[\W_]+",
        "",
        cleaned,
    )

    return not cleaned
