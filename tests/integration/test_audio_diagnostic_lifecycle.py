from itertools import count
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from .test_always_on_end_to_end import pipeline, module, scripted_run
from offline_ai_companion.audio.continuous_recorder import ContinuousRecorder
from offline_ai_companion.audio.half_duplex import HalfDuplexAudio
from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.core.privacy import SoftwareMute


def synthetic_stream(monkeypatch, blocks, status=None, on_exit=None):
    instances = []
    class Stream:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.callback = kwargs["callback"]
            self.closed = False
            instances.append(self)
        def __enter__(self):
            for block in blocks:
                self.callback(block, len(block), None, status)
            return self
        def __exit__(self, *args):
            self.closed = True
            if on_exit:
                on_exit()
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Stream)
    ticks = count()
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.time.monotonic", lambda: next(ticks) * .1)
    return instances


def speech_blocks():
    return [np.full((1600, 1), .1, dtype=np.float32) for _ in range(3)] + [np.zeros((1600, 1), dtype=np.float32) for _ in range(4)]


def test_application_queue_overflow_counted_and_corrupt_utterance_discarded(tmp_path, monkeypatch, caplog):
    recorder = ContinuousRecorder(queue_size=2)
    streams = synthetic_stream(monkeypatch, speech_blocks())
    target = tmp_path / "overflow.wav"
    assert recorder.record_utterance(target) is None
    assert recorder.last_capture_stats == {"dropped_blocks": 5, "input_overflows": 0}
    assert streams[0].closed and not target.exists()
    assert "dropped_blocks=5" in caplog.text


def test_backend_overflow_counted_without_logging_status_or_samples(tmp_path, monkeypatch, caplog):
    recorder = ContinuousRecorder()
    class Status:
        input_overflow = True
        def __str__(self):
            raise AssertionError("Private status must not be formatted")
    streams = synthetic_stream(monkeypatch, speech_blocks(), Status())
    assert recorder.record_utterance(tmp_path / "invalid.wav") is None
    assert recorder.last_capture_stats["input_overflows"] == 7
    assert streams[0].closed and "input_overflows=7" in caplog.text


def test_retired_stream_callback_never_requeues_audio(tmp_path, monkeypatch):
    recorder = ContinuousRecorder(silence_duration=.15)
    streams = synthetic_stream(monkeypatch, speech_blocks())
    assert recorder.record_utterance(tmp_path / "valid.wav")
    stats = recorder.last_capture_stats.copy()
    old_data = Mock()
    streams[0].callback(old_data, 1600, None, None)
    old_data.copy.assert_not_called()
    assert recorder.last_capture_stats == stats


def test_real_recorder_reopens_after_mute_without_stale_preroll(tmp_path, monkeypatch):
    recorder = ContinuousRecorder(silence_duration=.15)
    recorder.privacy = SoftwareMute()
    streams = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.closed = False
            streams.append(self)
        def __enter__(self):
            if len(streams) == 1:
                self.callback(np.full((1600, 1), .9, dtype=np.float32), 1600, None, None)
                recorder.privacy.set_muted(True)
            else:
                for block in speech_blocks():
                    self.callback(block, len(block), None, None)
            return self
        def __exit__(self, *args):
            self.closed = True
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Stream)
    ticks = count()
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.time.monotonic", lambda: next(ticks) * .1)
    path = tmp_path / "capture.wav"
    assert recorder.record_utterance(path) is None and streams[0].closed
    assert recorder.record_utterance(path) is None and len(streams) == 1
    recorder.privacy.set_muted(False)
    assert recorder.record_utterance(path) == path and streams[1].closed
    audio, _ = sf.read(path)
    assert np.max(audio) < .2  # muted stream's .9 samples never reappear


def test_half_duplex_capture_closes_before_playback_and_fresh_capture_reopens():
    gate = HalfDuplexAudio()
    entered, closed, played = Event(), Event(), Event()
    old = []
    def capture():
        with gate.capture(Event()) as ticket:
            old.append(ticket)
            entered.set()
            assert ticket.cancel.wait(3)
            closed.set()
    thread = Thread(target=capture)
    thread.start()
    try:
        assert entered.wait(3)
        with gate.playback():
            assert closed.is_set()
            played.set()
            assert not gate.valid(old[0].generation)
    finally:
        thread.join(3)
    assert not thread.is_alive() and played.is_set() and old[0].cancel.is_set()
    with gate.capture(Event()) as fresh:
        assert fresh and not fresh.cancel.is_set() and gate.valid(fresh.generation)


def test_capture_waiting_for_playback_stops_without_opening_stream():
    gate = HalfDuplexAudio()
    stopped, waiting = Event(), Event()
    tickets = []
    with gate.playback():
        def capture():
            waiting.set()
            with gate.capture(stopped) as ticket:
                tickets.append(ticket)
        thread = Thread(target=capture)
        thread.start()
        assert waiting.wait(3)
        stopped.set()
        thread.join(3)
        assert not thread.is_alive() and tickets == [None]


@pytest.mark.parametrize("where", ["transcription", "processing", "synthesis", "playback"])
def test_failures_identified_by_stage_without_private_details(pipeline, monkeypatch, capsys, where):
    app, _, _, _ = pipeline
    monkeypatch.setenv("NOVA_AUDIO_DIAGNOSTICS", "true")
    if where == "transcription":
        app.stt.transcribe.side_effect = RuntimeError("private transcript password is hunter2")
        app.process_recording(app.input_path)
    else:
        if where == "processing":
            app.assistant.process = Mock()
        component = {"processing": app.assistant.process, "synthesis": app.tts.synthesize, "playback": app.player.play}[where]
        component.side_effect = RuntimeError("private transcript password is hunter2")
        app.handle_transcript("Nova, explain a compiler")
    output = capsys.readouterr().out
    assert f"stage={where} status=error error_type=RuntimeError" in output
    assert "hunter2" not in output and "private transcript" not in output


def test_pipeline_after_shutdown_rejects_stale_recording_and_transcript(pipeline):
    app, repo, _, _ = pipeline
    scripted_run(app, [])
    app.stt.transcribe.return_value = "Nova, add a task to stale command"
    app.process_recording(app.input_path, accepted=True)
    app.handle_transcript("Nova, add a task to stale command", accepted_shutdown=True)
    app.speak("stale response")
    app.stt.transcribe.assert_not_called()
    app.player.play.assert_not_called()
    assert repo.list_tasks() == [] and app.passive_worker.queue.empty()


@pytest.mark.parametrize("text", ["Nova, add a task to stale command", "I was born in Bihar."])
def test_stop_during_transcription_does_not_dispatch_stale_audio(pipeline, text):
    app, repo, _, _ = pipeline
    def transcribe(path):
        app.stop_event.set()
        return text
    app.stt.transcribe.side_effect = transcribe
    app.process_recording(app.input_path)
    assert repo.list_tasks() == [] and app.passive_worker.queue.empty()
    app.tts.synthesize.assert_not_called()


@pytest.mark.parametrize("text", ["Nova, add a task to echo command", "I love playing cricket."])
def test_playback_invalidates_inflight_transcription_not_new_memory(pipeline, text):
    app, repo, _, _ = pipeline
    def transcribe(path):
        app.speak("Nova, this is synthetic playback")
        return text
    app.stt.transcribe.side_effect = transcribe
    app.process_recording(app.input_path)
    assert repo.list_tasks() == [] and app.passive_worker.queue.empty()
    assert app.player.play.call_count == 1


def test_playback_text_cannot_be_dispatched_while_playback_active(pipeline):
    app, repo, _, _ = pipeline
    def play(path):
        app.handle_transcript("Nova, add a task to self echo")
        app.handle_transcript("I love playing cricket.")
    app.player.play.side_effect = play
    app.speak("Nova, add a task to self echo")
    assert repo.list_tasks() == [] and app.passive_worker.queue.empty()


def test_synthesis_failure_releases_playback_guard(pipeline):
    app, _, _, _ = pipeline
    app.tts.synthesize.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError):
        app.speak("response")
    with app.audio_gate.capture(app.stop_event) as ticket:
        assert ticket and app.audio_gate.valid(ticket.generation)


def test_input_and_output_device_selection(tmp_path, monkeypatch):
    recorder = ContinuousRecorder(device=4, silence_duration=.15)
    streams = synthetic_stream(monkeypatch, speech_blocks())
    target = tmp_path / "audio.wav"
    assert recorder.record_utterance(target)
    assert streams[0].options["device"] == 4
    play, wait, stop = Mock(), Mock(), Mock()
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.play", play)
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.wait", wait)
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.stop", stop)
    AudioPlayer(device=7).play(target)
    assert play.call_args.kwargs["device"] == 7 and wait.called and stop.called


def test_voice_loop_closes_real_adapter_stream_before_playback_then_reopens(pipeline, monkeypatch):
    app, _, _, _ = pipeline
    app.recorder = ContinuousRecorder(silence_duration=.15)
    streams = synthetic_stream(monkeypatch, speech_blocks())
    original = app.recorder.record_utterance
    attempts = [0]
    def record(*args, **kwargs):
        attempts[0] += 1
        if attempts[0] > 2:
            raise KeyboardInterrupt
        if attempts[0] == 2:
            assert app.player.play.call_count == 1 and streams[0].closed
        return original(*args, **kwargs)
    app.recorder.record_utterance = record
    app.stt.transcribe.return_value = "Nova, where was I born?"
    def play(path):
        assert all(stream.closed for stream in streams)
    app.player.play.side_effect = play
    app.run()
    assert len(streams) == 2 and all(stream.closed for stream in streams)
    assert app.stt.transcribe.call_count == 2 and app.player.play.call_count == 2


def test_playback_interrupts_real_capture_waits_for_close_and_discards_frames(pipeline, monkeypatch):
    app, _, _, _ = pipeline
    app.recorder = ContinuousRecorder()
    entered, closed = Event(), Event()
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
        def __enter__(self):
            self.callback(np.full((1600, 1), .1, dtype=np.float32), 1600, None, None)
            entered.set()
            return self
        def __exit__(self, *args):
            closed.set()
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Stream)
    paths = []
    def capture():
        with app.audio_gate.capture(app.stop_event) as ticket:
            app.recorder.playback_cancel = ticket.cancel
            paths.append(app.recorder.record_utterance(app.input_path, app.stop_event))
    thread = Thread(target=capture)
    thread.start()
    app.player.play.side_effect = lambda path: closed.is_set() or pytest.fail("Playback overlapped input")
    try:
        assert entered.wait(3)
        app.speak("A harmless test response")
    finally:
        app.stop_event.set()
        thread.join(3)
    assert not thread.is_alive() and closed.is_set() and paths == [None]
    assert not app.input_path.exists()
    app.stt.transcribe.assert_not_called()


def test_stream_closes_on_vad_failure_then_can_reopen(tmp_path, monkeypatch):
    recorder = ContinuousRecorder(silence_duration=.15)
    streams = synthetic_stream(monkeypatch, speech_blocks())
    original = recorder.vad.is_speech
    recorder.vad.is_speech = Mock(side_effect=RuntimeError("private details"))
    with pytest.raises(RuntimeError):
        recorder.record_utterance(tmp_path / "failed.wav")
    assert streams[0].closed
    recorder.vad.is_speech = original
    assert recorder.record_utterance(tmp_path / "fresh.wav")
    assert streams[1].closed


def test_close_failure_does_not_report_successful_stream_close(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NOVA_AUDIO_DIAGNOSTICS", "true")
    recorder = ContinuousRecorder(silence_duration=.15)
    def fail():
        raise RuntimeError("private close error")
    synthetic_stream(monkeypatch, speech_blocks(), on_exit=fail)
    with pytest.raises(RuntimeError):
        recorder.record_utterance(tmp_path / "failed.wav")
    output = capsys.readouterr().out
    assert "event=stream_close_failed" in output and "event=stream_closed" not in output
    assert "private" not in output


def test_output_underrun_report_is_numeric_only(tmp_path, monkeypatch, caplog):
    path = tmp_path / "audio.wav"
    sf.write(path, np.zeros(20), 22050)
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.play", Mock())
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.wait", Mock(return_value=SimpleNamespace(output_underflow=True)))
    stop = Mock()
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.stop", stop)
    AudioPlayer().play(path)
    assert "output_underflows=1" in caplog.text
    stop.assert_called_once()


def test_failed_playback_settles_before_capture_is_allowed(pipeline, monkeypatch):
    app, repo, _, _ = pipeline
    app.player.play.side_effect = RuntimeError("partial playback failed")
    delays = []
    def settle(seconds):
        delays.append(seconds)
        assert app.audio_gate.playback_pending == 1
        app.handle_transcript("Nova, add a task to self echo")
    monkeypatch.setattr(module.time, "sleep", settle)
    with pytest.raises(RuntimeError):
        app.speak("A response")
    assert delays == [.3] and app.audio_gate.playback_pending == 0
    assert repo.list_tasks() == [] and app.passive_worker.queue.empty()


def test_transcript_only_injected_instance_lazily_initializes_shutdown_guard():
    app = module.AlwaysOnAssistant.__new__(module.AlwaysOnAssistant)
    assert not app.stop_event.is_set()
    event = app.stop_event
    assert app.stop_event is event
    replacement = Event()
    app.stop_event = replacement
    assert app.stop_event is replacement
    app.stop_event.set()
    # A stopped transcript-only instance exits before needing hardware/models.
    app.handle_transcript("Nova, do not process this stale command")
