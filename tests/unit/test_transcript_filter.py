
from offline_ai_companion.stt.transcript_filter import (
    is_invalid_transcript,
    strip_audio_captions,
)
import pytest


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


@pytest.mark.parametrize("transcript", [
    "[XBOX SOUND] [MUSIC]", "[APPLAUSE] (dramatic music)",
    "[blank_audio] [no speech]", "(background noise)", None, 123,
])
def test_combined_captions_and_invalid_types(transcript):
    assert is_invalid_transcript(transcript)


def test_captions_removed_without_losing_spoken_content():
    assert strip_audio_captions("[MUSIC] I love playing cricket. [XBOX SOUND]") == "I love playing cricket."
    assert not is_invalid_transcript("[MUSIC] I love playing cricket.")


def test_parenthetical_spoken_content_is_preserved():
    assert strip_audio_captions("I enjoy music (especially jazz).") == "I enjoy music (especially jazz)."
