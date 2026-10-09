
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    PROJECT_ROOT / "scripts" / "always_on_assistant.py"
)

spec = importlib.util.spec_from_file_location(
    "wake_activated_assistant",
    SCRIPT_PATH,
)

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

AlwaysOnAssistant = module.AlwaysOnAssistant


@pytest.fixture
def assistant():
    """Create an isolated assistant without hardware."""

    instance = AlwaysOnAssistant.__new__(
        AlwaysOnAssistant
    )

    instance.activation_controller = (
        module.ActivationController()
    )

    instance.assistant = Mock()
    instance.assistant.process.return_value = (
        "Your presentation is tomorrow."
    )

    instance.passive_memory_enabled = True
    instance.passive_worker = Mock()
    instance.passive_worker.submit.return_value = True

    instance.speak = Mock()
    instance.set_state = Mock()

    instance.output_path = Path(
        "test_response.wav"
    )

    return instance


def test_background_speech_never_speaks(assistant):
    assistant.handle_transcript(
        "I have a presentation tomorrow"
    )

    assistant.passive_worker.submit.assert_called_once_with(
        "I have a presentation tomorrow"
    )

    assistant.assistant.process.assert_not_called()
    assistant.speak.assert_not_called()


def test_wake_command_speaks(assistant):
    assistant.handle_transcript(
        "Nova, what presentations do I have?"
    )

    assistant.assistant.process.assert_called_once_with(
        "what presentations do I have?"
    )

    assistant.speak.assert_called_once_with(
        "Your presentation is tomorrow.",
        assistant.output_path,
    )

    assistant.passive_worker.submit.assert_not_called()


def test_wake_name_alone_does_not_speak(assistant):
    assistant.handle_transcript(
        "Hey Nova"
    )

    assistant.assistant.process.assert_not_called()
    assistant.speak.assert_not_called()
    assistant.passive_worker.submit.assert_not_called()


def test_followup_after_wake_name(assistant):
    start = datetime(
        2026, 10, 9, 12, 0,
        tzinfo=timezone.utc,
    )

    assistant.handle_transcript(
        "Nova",
        captured_at=start,
    )

    assistant.handle_transcript(
        "What is my schedule?",
        captured_at=start + timedelta(seconds=3),
    )

    assistant.assistant.process.assert_called_once_with(
        "What is my schedule?"
    )

    assistant.speak.assert_called_once()


def test_expired_activation_is_passive(assistant):
    start = datetime(
        2026, 10, 9, 12, 0,
        tzinfo=timezone.utc,
    )

    assistant.handle_transcript(
        "Nova",
        captured_at=start,
    )

    assistant.handle_transcript(
        "I have a meeting tomorrow",
        captured_at=start + timedelta(seconds=10),
    )

    assistant.assistant.process.assert_not_called()
    assistant.speak.assert_not_called()

    assistant.passive_worker.submit.assert_called_once_with(
        "I have a meeting tomorrow"
    )


def test_passive_memory_disabled(assistant):
    assistant.passive_memory_enabled = False
    assistant.passive_worker = None

    assistant.handle_transcript(
        "I have a meeting tomorrow"
    )

    assistant.assistant.process.assert_not_called()
    assistant.speak.assert_not_called()


def test_invalid_transcript_is_ignored(assistant):
    assistant.handle_transcript(
        "[silence]"
    )

    assistant.assistant.process.assert_not_called()
    assistant.passive_worker.submit.assert_not_called()
    assistant.speak.assert_not_called()


def test_active_processing_failure_does_not_speak(
    assistant,
):
    assistant.assistant.process.side_effect = (
        RuntimeError("Processing failed")
    )

    assistant.handle_transcript(
        "Nova, what is my schedule?"
    )

    assistant.speak.assert_not_called()
    assistant.passive_worker.submit.assert_not_called()


def test_passive_queue_failure_does_not_speak(
    assistant,
):
    assistant.passive_worker.submit.return_value = False

    assistant.handle_transcript(
        "I need to finish my project"
    )

    assistant.assistant.process.assert_not_called()
    assistant.speak.assert_not_called()


@pytest.mark.parametrize("transcript", ["[XBOX SOUND] [MUSIC]", "(applause) [noise]", "...!!!"])
def test_combined_captions_never_reach_passive_queue(assistant, transcript):
    assistant.handle_transcript(transcript)
    assistant.passive_worker.submit.assert_not_called()
    assistant.assistant.process.assert_not_called()
    assistant.speak.assert_not_called()


def test_caption_before_wake_word_does_not_hide_activation(assistant):
    assistant.handle_transcript("[MUSIC] Nova, where was I born?")
    assistant.assistant.process.assert_called_once_with("where was I born?")
    assistant.passive_worker.submit.assert_not_called()


def test_passive_speech_with_captions_is_cleaned(assistant):
    assistant.handle_transcript("[MUSIC] I love playing cricket. [XBOX SOUND]")
    assistant.passive_worker.submit.assert_called_once_with("I love playing cricket.")
    assistant.speak.assert_not_called()
