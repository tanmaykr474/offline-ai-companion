import logging
import subprocess
import traceback
from pathlib import Path
from unittest.mock import Mock

import pytest

from offline_ai_companion.audio.temporary import TemporaryAudio
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.tts.piper import PiperTTS
from .test_always_on_end_to_end import module, pipeline


@pytest.fixture
def owned_pipeline(pipeline, tmp_path):
    app, facts, processor, llm = pipeline
    app._temporary_audio = TemporaryAudio(tmp_path)
    app.input_path = app._temporary_audio.path("input.wav")
    app.output_path = app._temporary_audio.path("response.wav")
    app.reminder_output_path = app._temporary_audio.path("reminder.wav")
    yield pipeline
    if app._temporary_audio.root.exists():
        app._temporary_audio.close()


@pytest.mark.parametrize("phase", ["normal", "stt_error", "interrupt", "muted", "mute_during_stt"])
def test_owned_input_removed_on_every_processing_exit(owned_pipeline, phase):
    app, _, _, _ = owned_pipeline
    app.input_path.write_bytes(b"private audio")
    app.stt.transcribe.return_value = "Nova, what is my name?"
    if phase == "stt_error":
        app.stt.transcribe.side_effect = RuntimeError("private speech dont-save-THIS")
    elif phase == "interrupt":
        app.stt.transcribe.side_effect = KeyboardInterrupt
    elif phase == "muted":
        app.set_muted(True)
    elif phase == "mute_during_stt":
        def transcribe(path):
            app.set_muted(True)
            return "My favorite food is pasta."
        app.stt.transcribe.side_effect = transcribe
    if phase == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            app.process_recording(app.input_path)
    else:
        app.process_recording(app.input_path)
    assert not app.input_path.exists()
    assert app.assistant.passive_memory_repository.list_memories() == []
    if phase in {"muted", "mute_during_stt"}:
        app.player.play.assert_not_called()


def test_user_provided_audio_is_not_removed(owned_pipeline, tmp_path):
    app, _, _, _ = owned_pipeline
    user_file = tmp_path / "retained.wav"
    user_file.write_bytes(b"user recording")
    app.stt.transcribe.return_value = "Nova, what is my name?"
    app.process_recording(user_file)
    assert user_file.read_bytes() == b"user recording"


@pytest.mark.parametrize("failure", [None, "tts", "playback", "interrupt"])
def test_output_removed_after_playback_or_failure(owned_pipeline, failure):
    app, _, _, _ = owned_pipeline
    def synthesize(text, path):
        path.write_bytes(b"private response")
        if failure == "tts":
            raise RuntimeError("dont-save-THIS")
        return path
    app.tts.synthesize.side_effect = synthesize
    if failure == "playback":
        app.player.play.side_effect = RuntimeError("dont-save-THIS")
    elif failure == "interrupt":
        app.player.play.side_effect = KeyboardInterrupt
    if failure:
        with pytest.raises(KeyboardInterrupt if failure == "interrupt" else RuntimeError):
            app.speak("A personal answer.")
    else:
        app.speak("A personal answer.")
    assert not app.output_path.exists()


@pytest.mark.parametrize("result", ["cancel", "error", "shutdown"])
def test_partial_capture_cleaned_on_cancel_error_and_shutdown(owned_pipeline, result):
    app, _, _, _ = owned_pipeline
    calls = 0
    def record(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            app.input_path.write_bytes(b"partial private audio")
            if result == "shutdown":
                raise KeyboardInterrupt
            if result == "error":
                raise RuntimeError("private speech dont-save-THIS")
            return None
        assert not app.input_path.exists()
        raise KeyboardInterrupt
    app.recorder.record_utterance.side_effect = record
    app.run()
    assert not app._temporary_audio.root.exists()
    app.stt.transcribe.assert_not_called()


def test_cleanup_preserves_unowned_or_intentionally_retained_files(tmp_path):
    owner = TemporaryAudio(tmp_path)
    external = tmp_path / "user.wav"
    external.write_bytes(b"saved")
    retained = owner.root / "intentionally-retained.wav"
    retained.write_bytes(b"saved")
    private = owner.path("input.wav")
    private.write_bytes(b"temporary")
    owner.cleanup(external)
    owner.close()
    assert not private.exists()
    assert retained.exists() and external.exists()


def test_cleanup_failure_reports_only_category(tmp_path, monkeypatch, caplog):
    owner = TemporaryAudio(tmp_path)
    private = owner.path("input.wav")
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path == private:
            raise PermissionError("private path dont-save-THIS")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail)
    caplog.set_level(logging.ERROR)
    owner.cleanup(private)
    assert "PermissionError" in caplog.text
    assert "dont-save-THIS" not in caplog.text
    monkeypatch.setattr(Path, "unlink", original)
    owner.close()


def test_active_and_reminder_console_diagnostics_do_not_expose_contents(owned_pipeline, capsys):
    app, _, _, _ = owned_pipeline
    app.assistant.process = Mock(return_value="private personal answer dont-save-THIS")
    app.handle_transcript("Nova, private personal question dont-save-THIS")
    notification = Mock()
    notification.reminder.message = "private reminder dont-save-THIS"
    app.notifications = Mock()
    app.notifications.get_pending.side_effect = [notification, None]
    app.deliver_pending_reminders()
    assert "dont-save-THIS" not in capsys.readouterr().out
    assert app.tts.synthesize.call_count == 2


@pytest.mark.parametrize("component", ["stt", "tts"])
def test_subprocess_stderr_not_exposed_in_printed_traceback(tmp_path, monkeypatch, component):
    executable, model, audio = (tmp_path / name for name in ("program.exe", "model.bin", "audio.wav"))
    for path in (executable, model, audio):
        path.touch()
    failure = subprocess.CalledProcessError(1, "program", stderr="private speech dont-save-THIS")
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(RuntimeError) as exc:
        if component == "stt":
            WhisperSTT(executable, model).transcribe(audio)
        else:
            PiperTTS(executable, model).synthesize("private answer", audio)
    formatted = "".join(traceback.format_exception(exc.value))
    assert "dont-save-THIS" not in formatted


def test_direct_piper_input_redacts_credentials_and_preserves_requested_output(tmp_path, monkeypatch):
    executable, model, output = (tmp_path / name for name in ("program.exe", "voice.onnx", "retained.wav"))
    executable.touch()
    model.touch()
    inputs = []
    def run(*args, **kwargs):
        inputs.append(kwargs["input"])
        output.write_bytes(b"safe synthesized output")
    monkeypatch.setattr(subprocess, "run", run)
    PiperTTS(executable, model).synthesize("password: dont-save-THIS", output)
    assert "dont-save-THIS" not in inputs[0]
    assert output.exists()  # Caller-requested output is not runtime-owned.
