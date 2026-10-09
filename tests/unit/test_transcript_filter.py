
from offline_ai_companion.stt.transcript_filter import (
    is_invalid_transcript,
)


def test_rejects_empty_transcript():
    assert is_invalid_transcript("")


def test_rejects_whitespace():
    assert is_invalid_transcript("   ")


def test_rejects_inaudible_transcript():
    assert is_invalid_transcript(
        "[inaudible] [inaudible] [inaudible]"
    )


def test_rejects_silence():
    assert is_invalid_transcript("[silence]")


def test_rejects_music():
    assert is_invalid_transcript("[music]")


def test_rejects_punctuation():
    assert is_invalid_transcript("...!!!")


def test_accepts_normal_speech():
    assert not is_invalid_transcript(
        "Remind me to drink water"
    )


def test_accepts_speech_with_marker():
    assert not is_invalid_transcript(
        "[inaudible] Remind me to drink water"
    )


def test_rejects_case_insensitive_markers():
    assert is_invalid_transcript(
        "[INAUDIBLE] [Silence]"
    )
