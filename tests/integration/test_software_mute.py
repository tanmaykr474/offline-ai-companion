from threading import Event, Thread
from unittest.mock import Mock

import numpy as np
import pytest

from .test_always_on_end_to_end import pipeline, module
from offline_ai_companion.audio.continuous_recorder import ContinuousRecorder
from offline_ai_companion.core.privacy import SoftwareMute, WindowsMuteHotkey
from offline_ai_companion.core.state import AssistantState


@pytest.mark.parametrize("text", ["I was born in Bihar.", "Nova, where was I born?"])
def test_muted_transcripts_do_not_reach_any_processing(pipeline, text, capsys):
    app, _, _, llm = pipeline
    app.set_muted(True)
    app.handle_transcript(text)
    app.process_recording(app.input_path)
    app.stt.transcribe.assert_not_called()
    app.tts.synthesize.assert_not_called()
    llm.generate.assert_not_called()
    assert app.passive_worker.queue.empty()
    assert "Bihar" not in capsys.readouterr().out
    assert app.state == AssistantState.MUTED


@pytest.mark.parametrize("unmute", [False, True])
def test_inflight_transcription_crossing_mute_boundary_is_discarded(pipeline, unmute, capsys):
    app, _, _, _ = pipeline

    def transcribe(path):
        app.set_muted(True)
        if unmute:
            app.set_muted(False)
        return "Nova, private transcript"

    app.stt.transcribe.side_effect = transcribe
    app.process_recording(app.input_path)
    app.tts.synthesize.assert_not_called()
    assert app.passive_worker.queue.empty()
    assert "private transcript" not in capsys.readouterr().out


def test_transcription_error_after_mute_does_not_expose_stderr(pipeline, capsys):
    app, _, _, _ = pipeline

    def transcribe(path):
        app.set_muted(True)
        raise RuntimeError("private transcript in subprocess stderr")

    app.stt.transcribe.side_effect = transcribe
    app.process_recording(app.input_path)
    assert "private" not in capsys.readouterr().out


def test_completed_recording_crossing_fast_mute_unmute_skips_stt(pipeline):
    app, _, _, _ = pipeline

    def record(*args, **kwargs):
        app.set_muted(True)
        app.set_muted(False)
        app.stop_event.set()
        return app.input_path

    app.recorder.record_utterance.side_effect = record
    app.run()
    app.stt.transcribe.assert_not_called()
    assert app.passive_worker.queue.empty()


def test_muted_loop_does_not_capture_and_resumes_after_unmute(pipeline):
    app, _, _, _ = pipeline
    app.set_muted(True)
    entered_wait = Event()
    original_wait = app.stop_event.wait

    def wait(timeout):
        app.recorder.record_utterance.assert_not_called()
        entered_wait.set()
        return original_wait(timeout)

    app.stop_event.wait = wait

    def unmute():
        assert entered_wait.wait(3)
        app.set_muted(False)

    thread = Thread(target=unmute)
    thread.start()

    def record(*args, **kwargs):
        app.stop_event.set()
        return None

    app.recorder.record_utterance.side_effect = record
    try:
        app.run()
    finally:
        app.stop_event.set()
        thread.join(3)
    app.recorder.record_utterance.assert_called_once()


def test_accepted_passive_queue_drains_while_muted_and_rejects_new_work(pipeline):
    app, _, processor, _ = pipeline
    entered, release = Event(), Event()
    original = processor.process

    def process(text):
        entered.set()
        assert release.wait(3)
        return original(text)

    processor.process = process
    app.passive_worker.privacy = app.privacy
    app.passive_worker.start()
    try:
        app.handle_transcript("I was born in Bihar.")
        assert entered.wait(3)
        app.handle_transcript("I love playing cricket.")
        app.set_muted(True)
        assert not app.passive_worker.submit("I was born in Kerala.")
        app.handle_transcript("I was born in Kerala.")
        assert not app.passive_worker.stop(timeout=0)
    finally:
        release.set()
        assert app.passive_worker.stop(timeout=3)
    assert len(app.assistant.passive_memory_repository.list_memories()) == 2
    assert app.passive_worker.queue.unfinished_tasks == 0
    app.player.play.assert_not_called()


def test_active_command_admitted_before_mute_may_finish_but_response_is_withheld(pipeline, capsys):
    app, _, _, _ = pipeline

    def process(text):
        app.set_muted(True)
        return "private answer"

    app.assistant.process = Mock(side_effect=process)
    app.handle_transcript("Nova, hello")
    app.assistant.process.assert_called_once_with("hello")
    app.player.play.assert_not_called()
    assert "private answer" not in capsys.readouterr().out


def test_mute_clears_wake_followup_and_new_capture_can_be_processed(pipeline):
    app, _, _, _ = pipeline
    app.handle_transcript("Nova")
    assert app.activation_controller.active_until is not None
    app.set_muted(True)
    app.set_muted(False)
    assert app.activation_controller.active_until is None
    app.handle_transcript("Nova, where was I born?")
    app.player.play.assert_called_once()


def test_acceptance_guard_serializes_mute_with_submission():
    privacy = SoftwareMute()
    generation, cancel = privacy.snapshot()
    started, finished = Event(), Event()

    def mute():
        started.set()
        privacy.set_muted(True)
        finished.set()

    with privacy.guard(generation) as allowed:
        assert allowed
        thread = Thread(target=mute)
        thread.start()
        assert started.wait(3)
        assert not finished.is_set()
    thread.join(3)
    assert finished.is_set() and cancel.is_set()
    with privacy.guard(generation) as allowed:
        assert not allowed


@pytest.mark.parametrize("fast_unmute", [False, True])
def test_real_recorder_discards_inflight_frames_at_mute_boundary(tmp_path, monkeypatch, fast_unmute):
    recorder = ContinuousRecorder()
    recorder.privacy = SoftwareMute()
    closed = Event()

    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            self.callback(np.full((1600, 1), .1, dtype=np.float32), 1600, None, None)
            recorder.privacy.set_muted(True)
            if fast_unmute:
                recorder.privacy.set_muted(False)
            self.callback(np.full((1600, 1), .1, dtype=np.float32), 1600, None, None)
            return self

        def __exit__(self, *args):
            closed.set()

    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Stream)
    path = tmp_path / "cancelled.wav"
    assert recorder.record_utterance(path) is None
    assert closed.is_set()
    assert not path.exists()


def test_muted_recorder_never_opens_microphone(tmp_path, monkeypatch):
    recorder = ContinuousRecorder()
    recorder.privacy = SoftwareMute(muted=True)
    stream = Mock()
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", stream)
    assert recorder.record_utterance(tmp_path / "muted.wav") is None
    stream.assert_not_called()


def test_windows_console_m_key_toggles_mute_without_speech():
    toggled = Event()
    keyboard = Mock()
    keyboard.kbhit.return_value = True
    keyboard.getwch.return_value = "M"
    keys = WindowsMuteHotkey(toggled.set, keyboard)
    keys.start()
    try:
        assert toggled.wait(3)
    finally:
        keys.stop()
    assert not keys.thread.is_alive()


def test_microphone_disabled_configuration_initializes_muted_application(pipeline, tmp_path, monkeypatch):
    existing, _, _, _ = pipeline
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "MIC_ENABLED", False)
    monkeypatch.setattr(module, "PASSIVE_MEMORY_ENABLED", False)
    monkeypatch.setattr(module, "Assistant", lambda: existing.assistant)
    monkeypatch.setattr(module, "ContinuousRecorder", Mock)
    monkeypatch.setattr(module, "WhisperSTT", Mock)
    monkeypatch.setattr(module, "PiperTTS", Mock)
    monkeypatch.setattr(module, "AudioPlayer", Mock)
    app = module.AlwaysOnAssistant()
    assert app.privacy.muted
    app.process_recording(app.input_path)
    app.stt.transcribe.assert_not_called()
    app.set_muted(False)
    assert not app.privacy.muted


@pytest.mark.parametrize("state", [AssistantState.LISTENING, AssistantState.PROCESSING, AssistantState.SPEAKING])
def test_processing_state_updates_cannot_hide_mute(pipeline, state):
    app, _, _, _ = pipeline
    app.set_muted(True)
    app.set_state(state)
    assert app.state == AssistantState.MUTED


def test_repeated_mute_requests_are_idempotent():
    privacy = SoftwareMute()
    assert privacy.set_muted(True)
    generation, cancel = privacy.snapshot()
    assert not privacy.set_muted(True)
    assert privacy.snapshot() == (generation, cancel)
    assert privacy.set_muted(False)
    assert cancel.is_set()
    with privacy.guard(generation) as allowed:
        assert not allowed
