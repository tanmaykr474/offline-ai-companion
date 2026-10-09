
import pytest

from offline_ai_companion.core.wake_detector import (
    WakeDetector,
)


@pytest.fixture
def detector():
    return WakeDetector(
        assistant_name="Nova",
        wake_phrases=(
            "Nova",
            "hey Nova",
        ),
    )


@pytest.mark.parametrize(
    ("transcript", "expected_command"),
    [
        (
            "Nova, what is my schedule?",
            "what is my schedule?",
        ),
        (
            "Hey Nova, what is my name?",
            "what is my name?",
        ),
        (
            "Nova remind me to drink water",
            "remind me to drink water",
        ),
        (
            "Nova! Tell me a joke.",
            "Tell me a joke.",
        ),
        (
            "  Hey   Nova: show my tasks",
            "show my tasks",
        ),
        (
            "Nova",
            "",
        ),
        (
            "Hey Nova",
            "",
        ),
    ],
)
def test_valid_wake_phrases(
    detector,
    transcript,
    expected_command,
):
    result = detector.detect(transcript)

    assert result.activated is True
    assert result.command == expected_command
    assert result.wake_phrase is not None


@pytest.mark.parametrize(
    "transcript",
    [
        "",
        "   ",
        "I have a meeting tomorrow.",
        "My name is Nova.",
        "I was talking about Nova yesterday.",
        "Please call Nova later.",
        "Novai, what is my schedule?",
        "Hey there Nova",
        "The Nova project is ready.",
    ],
)
def test_background_speech_does_not_activate(
    detector,
    transcript,
):
    result = detector.detect(transcript)

    assert result.activated is False
    assert result.command == ""
    assert result.wake_phrase is None


def test_custom_wake_phrase():
    detector = WakeDetector(
        assistant_name="Nova",
        wake_phrases=("hello Nova",),
    )

    result = detector.detect(
        "Hello Nova, how are you?"
    )

    assert result.activated is True
    assert result.command == "how are you?"


def test_empty_assistant_name_is_rejected():
    with pytest.raises(ValueError):
        WakeDetector(
            assistant_name=" ",
            wake_phrases=("Nova",),
        )


def test_empty_wake_phrases_are_rejected():
    with pytest.raises(ValueError):
        WakeDetector(
            assistant_name="Nova",
            wake_phrases=(),
        )


def test_does_not_modify_original_transcript(detector):
    transcript = "Hey Nova, show my reminders"

    result = detector.detect(transcript)

    assert transcript == "Hey Nova, show my reminders"
    assert result.command == "show my reminders"


def Nova(detector):
    result = detector.detect(
        "Hey Nova, tell me something"
    )

    assert result.wake_phrase == "hey Nova"
    assert result.command == "tell me something"
