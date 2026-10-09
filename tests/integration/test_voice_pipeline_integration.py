
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import pytest

from offline_ai_companion.core.state import AssistantState

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "always_on_assistant.py"

spec = importlib.util.spec_from_file_location(
    "always_on_assistant",
    SCRIPT_PATH,
)

if spec is None or spec.loader is None:
    raise ImportError(f"Cannot load assistant script: {SCRIPT_PATH}")

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

AlwaysOnAssistant = module.AlwaysOnAssistant


@pytest.fixture
def app(tmp_path):
    """Create an isolated always-on assistant without real hardware."""

    with (
        patch("always_on_assistant.ContinuousRecorder"),
        patch("always_on_assistant.AudioPlayer"),
        patch("always_on_assistant.WhisperSTT"),
        patch("always_on_assistant.Assistant"),
        patch("always_on_assistant.PiperTTS"),
        patch("always_on_assistant.ReminderScheduler"),
        patch("always_on_assistant.ReminderNotifications"),
        patch("always_on_assistant.AudioRecovery"),
    ):
        instance = AlwaysOnAssistant()

    instance.input_path = tmp_path / "input.wav"
    instance.output_path = tmp_path / "response.wav"
    instance.reminder_output_path = tmp_path / "reminder.wav"

    instance.stop_event = Event()
    instance.notifications.interrupt = Event()
    instance.notifications.get_pending.return_value = None
    instance.scheduler.stop.return_value = True

    return instance


def stop_after_recording(app, result=None):
    """Simulate one recording attempt, then request shutdown."""

    def record(*args, **kwargs):
        app.stop_event.set()
        return result

    app.recorder.record_utterance.side_effect = record



def test_successful_voice_pipeline(app):
    """Verify wake -> STT -> Assistant -> TTS -> playback."""

    audio_path = Path("recorded.wav")

    def record(*args, **kwargs):
        app.stop_event.set()
        return audio_path

    app.recorder.record_utterance.side_effect = record

    app.stt.transcribe.return_value = (
        "Nova, hello companion"
    )

    app.assistant.process.return_value = (
        "Hello there"
    )

    with patch("always_on_assistant.time.sleep"):
        app.run()

    app.stt.transcribe.assert_called_once_with(
        audio_path
    )

    app.assistant.process.assert_called_once_with(
        "hello companion"
    )

    app.tts.synthesize.assert_called_once_with(
        "Hello there",
        app.output_path,
    )

    app.player.play.assert_called_once_with(
        app.output_path
    )


@pytest.mark.parametrize(
    "transcript",
    ["", "   ", "[silence]", "[music]", "..."],
)
def test_invalid_transcripts_are_ignored(app, transcript):
    stop_after_recording(app, Path("recorded.wav"))
    app.stt.transcribe.return_value = transcript

    app.run()

    app.assistant.process.assert_not_called()
    app.tts.synthesize.assert_not_called()
    app.player.play.assert_not_called()


def test_microphone_failure_invokes_recovery(app):
    error = RuntimeError("Microphone disconnected")

    def record(*args, **kwargs):
        app.stop_event.set()
        raise error

    app.recorder.record_utterance.side_effect = record

    app.run()

    app.audio_recovery.handle_failure.assert_called_once_with(
        "Microphone",
        error,
        app.stop_event,
    )
    app.stt.transcribe.assert_not_called()


def test_whisper_failure_invokes_recovery(app):
    error = RuntimeError("Whisper unavailable")
    stop_after_recording(app, Path("recorded.wav"))

    app.stt.transcribe.side_effect = error

    app.run()

    app.audio_recovery.handle_failure.assert_called_once_with(
        "Whisper STT",
        error,
        app.stop_event,
    )
    app.assistant.process.assert_not_called()


def test_assistant_processing_failure(app):
    stop_after_recording(app, Path("recorded.wav"))

    app.stt.transcribe.return_value = "Hello"
    app.assistant.process.side_effect = RuntimeError(
        "Processing failed"
    )

    app.run()

    app.tts.synthesize.assert_not_called()
    app.player.play.assert_not_called()


def test_piper_failure_is_handled(app):
    stop_after_recording(app, Path("recorded.wav"))

    app.stt.transcribe.return_value = "Hello"
    app.assistant.process.return_value = "Hello back"
    app.tts.synthesize.side_effect = RuntimeError(
        "Piper unavailable"
    )

    with patch("always_on_assistant.time.sleep"):
        app.run()

    app.player.play.assert_not_called()
    app.scheduler.stop.assert_called_once_with(timeout=5.0)



def test_speaker_failure_is_handled(app):
    stop_after_recording(
        app,
        Path("recorded.wav"),
    )

    app.stt.transcribe.return_value = (
        "Nova, hello"
    )

    app.assistant.process.return_value = (
        "Hello back"
    )

    app.player.play.side_effect = RuntimeError(
        "Speaker disconnected"
    )

    with patch("always_on_assistant.time.sleep"):
        app.run()

    app.assistant.process.assert_called_once_with(
        "hello"
    )

    app.tts.synthesize.assert_called_once_with(
        "Hello back",
        app.output_path,
    )

    app.player.play.assert_called_once_with(
        app.output_path
    )

    # Playback failure must not crash the assistant.
    assert app.stop_event.is_set()


def test_recorder_receives_shutdown_and_interrupt_events(app):
    stop_after_recording(app)

    app.run()

    app.recorder.record_utterance.assert_called_once_with(
        app.input_path,
        app.stop_event,
        interrupt_event=app.notifications.interrupt,
    )


def test_reminder_interrupt_skips_stt(app):
    def record(*args, **kwargs):
        app.notifications.interrupt.set()
        app.stop_event.set()
        return None

    app.recorder.record_utterance.side_effect = record

    app.run()

    app.stt.transcribe.assert_not_called()
    app.assistant.process.assert_not_called()


def test_graceful_shutdown_closes_components(app):
    stop_after_recording(app)

    app.run()

    assert app.stop_event.is_set()
    app.notifications.close.assert_called_once_with()
    app.scheduler.stop.assert_called_once_with(timeout=5.0)
    assert app.state == AssistantState.IDLE


def test_keyboard_interrupt_stops_application(app):
    app.recorder.record_utterance.side_effect = KeyboardInterrupt()

    app.run()

    app.notifications.close.assert_called_once()
    app.scheduler.stop.assert_called_once_with(timeout=5.0)
    assert app.stop_event.is_set()


def test_shutdown_waits_for_passive_drain_before_reporting_stopped(app, capsys):
    stop_after_recording(app)
    worker = Mock()
    worker.stop.side_effect = [False, False, True]
    app.passive_worker = worker
    app.run()
    assert worker.stop.call_count == 3
    output = capsys.readouterr().out
    assert "Finishing accepted background speech" in output
    assert output.index("Finishing accepted background speech") < output.index("Nova stopped.")

