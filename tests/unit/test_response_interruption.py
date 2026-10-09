from threading import Event
from unittest.mock import Mock
import subprocess
import sys
from threading import Timer

import httpx
import numpy as np
import pytest
import soundfile as sf

from offline_ai_companion.core.cancellation import (
    ResponseControl, ResponseInterrupted, cancellation_scope, check_cancel, current_cancel,
)
from offline_ai_companion.core.state import AssistantState as S, validate_transition
from offline_ai_companion.core.privacy import SoftwareMute
from offline_ai_companion.audio.stop_monitor import StopMonitor, is_spoken_stop
from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.audio.cancellable_subprocess import run_cancellable
from offline_ai_companion.llm.ollama import OllamaLLM


def test_stop_is_latched_and_old_tokens_cannot_interrupt_new_response():
    control = ResponseControl()
    first = control.begin()
    assert control.interrupt(first)
    assert not control.interrupt(first)
    second = control.begin()
    control.set_reference(second, "temporary private output")
    control.finish(first)
    assert not control.interrupt(first)
    assert control.current is second and not second.cancel.is_set()
    control.finish(second)
    assert second.reference == ""
    assert not control.interrupt()


def test_cancellation_context_resets_even_after_exception():
    event = Event()
    with pytest.raises(ResponseInterrupted):
        with cancellation_scope(event):
            event.set()
            check_cancel()
    assert current_cancel() is None


@pytest.mark.parametrize("text,accepted", [
    ("Nova, stop.", True), ("Hey Nova, stop!", True),
    ("stop", False), ("Nova, stop and save a task", False),
    ("I said Nova stop", False), ("[MUSIC]", False),
    ("Nova, what is my name?", False), ("I love playing cricket", False),
])
def test_only_exact_wake_stop_is_monitor_command(text, accepted):
    assert is_spoken_stop(text) is accepted


@pytest.mark.parametrize("reference", ["Say Nova, stop to interrupt.", "HEY NOVA STOP!", "Nova: stop."])
def test_reference_containing_stop_phrase_rejects_feedback(reference):
    assert not is_spoken_stop("Nova, stop", reference)


@pytest.mark.parametrize("previous,target", [(S.SPEAKING, S.INTERRUPTED),
    (S.INTERRUPTED, S.LISTENING), (S.INTERRUPTED, S.MUTED),
    (S.MUTED, S.SHUTTING_DOWN), (S.SHUTTING_DOWN, S.IDLE)])
def test_legal_interruption_transitions(previous, target):
    validate_transition(previous, target)


@pytest.mark.parametrize("previous,target", [(S.SHUTTING_DOWN, S.SPEAKING),
    (S.MUTED, S.PROCESSING), (S.INTERRUPTED, S.SPEAKING)])
def test_illegal_interruption_transitions(previous, target):
    with pytest.raises(ValueError):
        validate_transition(previous, target)


def test_owned_stream_aborts_between_blocks_without_global_stop(tmp_path, monkeypatch):
    path = tmp_path / "response.wav"
    sf.write(path, np.zeros(2000, dtype=np.float32), 1000)
    cancel = Event()
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    stream.write.side_effect = lambda _: cancel.set()
    factory = Mock(return_value=stream)
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.OutputStream", factory)
    global_stop = Mock()
    monkeypatch.setattr("offline_ai_companion.audio.player.sd.stop", global_stop)
    with pytest.raises(ResponseInterrupted):
        AudioPlayer(device=7).play(path, cancel_event=cancel)
    assert stream.write.call_count == 1
    stream.abort.assert_called_once()
    stream.__exit__.assert_called_once()
    global_stop.assert_not_called()
    assert factory.call_args.kwargs["device"] == 7


def test_cancel_before_owned_subprocess_never_launches(monkeypatch):
    cancel = Event()
    cancel.set()
    popen = Mock()
    monkeypatch.setattr("offline_ai_companion.audio.cancellable_subprocess.subprocess.Popen", popen)
    with pytest.raises(ResponseInterrupted):
        run_cancellable(["unused"], cancel_event=cancel)
    popen.assert_not_called()


def test_owned_subprocess_terminated_and_reaped_on_cancel(monkeypatch):
    cancel = Event()
    child = Mock()
    child.__enter__ = Mock(return_value=child)
    child.__exit__ = Mock(return_value=False)
    child.poll.return_value = None
    def pending(**kwargs):
        cancel.set()
        raise subprocess.TimeoutExpired("private", .1)
    calls = []
    def communicate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return pending(**kwargs)
        return "", ""
    child.communicate.side_effect = communicate
    monkeypatch.setattr("offline_ai_companion.audio.cancellable_subprocess.subprocess.Popen", Mock(return_value=child))
    with pytest.raises(ResponseInterrupted):
        run_cancellable(["owned"], cancel_event=cancel, input="private text")
    child.terminate.assert_called_once()
    assert len(calls) == 2 and calls[1]["timeout"] == 1


@pytest.mark.parametrize("before", [True, False])
def test_ollama_cancel_boundary_suppresses_request_or_result(monkeypatch, before):
    event = Event()
    llm = OllamaLLM()
    response = Mock()
    response.json.return_value = {"response": "should never be spoken"}
    def send(*args, **kwargs):
        event.set()
        return response
    send_mock = Mock(side_effect=send)
    monkeypatch.setattr(llm, "_send_request", send_mock)
    with pytest.raises(ResponseInterrupted):
        with cancellation_scope(event):
            if before:
                event.set()
            llm.generate("a question")
    assert send_mock.call_count == (0 if before else 1)


@pytest.mark.parametrize("mode", ["stop", "other", "stale", "mute", "phase", "failure"])
def test_monitor_isolated_and_rejects_stale_muted_or_feedback_capture(mode, caplog):
    control, privacy = ResponseControl(), SoftwareMute()
    token = control.begin()
    paths = []
    monitor = None
    def record(path, **kwargs):
        paths.append(path)
        path.write_bytes(b"private audio")
        if len(paths) > 1:
            monitor.stop_event.set()
            return None
        return path
    def transcribe(*args, **kwargs):
        if mode == "stale":
            control.begin()
        elif mode == "mute":
            privacy.set_muted(True)
            privacy.set_muted(False)
        elif mode == "phase":
            control.set_reference(token, "New playback phase")
        elif mode == "failure":
            raise OSError("private transcript must not be logged")
        return "Nova, stop" if mode != "other" else "Nova, add a task"
    stop = Mock(side_effect=lambda expected: control.interrupt(expected))
    monitor = StopMonitor(control, privacy, stop, recorder=Mock(record_utterance=record),
                          stt=Mock(transcribe=transcribe))
    monitor._run(token, monitor.stop_event)
    assert stop.call_count == (1 if mode == "stop" else 0)
    assert all(not path.exists() and not path.parent.exists() for path in paths)
    assert "private transcript" not in caplog.text


def test_monitor_has_bounded_capture_and_one_worker():
    control = ResponseControl()
    monitor = StopMonitor(control, SoftwareMute(), Mock())
    assert monitor.recorder.queue_size == 10
    assert monitor.recorder.max_duration == 3


def test_owned_real_subprocess_cancellation_reaps_child(tmp_path):
    cancel = Event()
    timer = Timer(.2, cancel.set)
    timer.start()
    try:
        with pytest.raises(ResponseInterrupted):
            run_cancellable([sys.executable, "-c", "import time; time.sleep(20)"],
                            cancel_event=cancel, timeout=3)
    finally:
        timer.cancel()
        timer.join()


def test_owned_subprocess_timeout_is_bounded():
    with pytest.raises(subprocess.TimeoutExpired):
        run_cancellable([sys.executable, "-c", "import time; time.sleep(20)"],
                        cancel_event=Event(), timeout=.1)


def test_piper_cancellation_removes_partial_output_not_model(tmp_path, monkeypatch):
    from offline_ai_companion.tts.piper import PiperTTS
    executable, model, output = [tmp_path / name for name in ("piper.exe", "model.onnx", "output.wav")]
    executable.touch()
    model.write_bytes(b"model")
    def synthesis(*args, **kwargs):
        output.write_bytes(b"partial speech")
        raise ResponseInterrupted()
    monkeypatch.setattr("offline_ai_companion.tts.piper.run_cancellable", synthesis)
    with pytest.raises(ResponseInterrupted):
        PiperTTS(executable, model).synthesize("Hello", output, cancel_event=Event())
    assert not output.exists() and model.read_bytes() == b"model"


@pytest.mark.parametrize("failure", ["timeout", "connect", "server"])
def test_cancelled_ollama_error_never_retries(monkeypatch, failure):
    event = Event()
    request = httpx.Request("POST", "http://localhost:11434/api/generate")
    errors = {
        "timeout": httpx.ReadTimeout("private", request=request),
        "connect": httpx.ConnectError("private", request=request),
        "server": httpx.HTTPStatusError("private", request=request, response=httpx.Response(503)),
    }
    def send(payload):
        event.set()
        raise errors[failure]
    llm = OllamaLLM(max_retries=3)
    sender = Mock(side_effect=send)
    monkeypatch.setattr(llm, "_send_request", sender)
    with pytest.raises(ResponseInterrupted):
        with cancellation_scope(event):
            llm.generate("Hello")
    assert sender.call_count == 1


def test_monitor_restart_closes_old_capture_before_next_worker():
    control, entered = ResponseControl(), Event()
    def record(path, stop_event):
        entered.set()
        while not stop_event.is_set():
            Event().wait(.005)
        return None
    monitor = StopMonitor(control, SoftwareMute(), Mock(), recorder=Mock(record_utterance=record), stt=Mock())
    first = control.begin()
    monitor.start(first)
    assert entered.wait(3)
    old_thread = monitor.thread
    monitor.start(first)
    assert monitor.thread is old_thread
    assert monitor.stop(timeout=3)
    entered.clear()
    second = control.begin()
    monitor.start(second)
    assert entered.wait(3)
    assert monitor.thread is not old_thread and not old_thread.is_alive()
    assert monitor.stop(timeout=3)


def test_windows_s_key_is_explicit_opt_in():
    from offline_ai_companion.core.privacy import WindowsMuteHotkey
    for enabled in (False, True):
        stop, mute = Mock(), Mock()
        keys = iter(["s", "m"])
        hotkey = None
        def next_key():
            key = next(keys)
            if key == "m":
                hotkey.stop_event.set()
            return key
        keyboard = Mock(kbhit=lambda: True, getwch=next_key)
        hotkey = WindowsMuteHotkey(mute, keyboard=keyboard, interrupt=stop if enabled else None)
        hotkey._run()
        assert stop.call_count == int(enabled)
        mute.assert_called_once()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "121", "private-invalid-value"])
def test_timeout_configuration_rejects_invalid_values_without_echo(monkeypatch, value):
    from offline_ai_companion.config import _interruption_timeout
    monkeypatch.setenv("NOVA_INTERRUPT_STT_TIMEOUT", value)
    with pytest.raises(ValueError) as error:
        _interruption_timeout("NOVA_INTERRUPT_STT_TIMEOUT", "5")
    assert "private-invalid-value" not in str(error.value)


def test_spoken_monitor_requires_experimental_opt_in():
    import os
    env = dict(os.environ, NOVA_SPOKEN_INTERRUPTION="true", NOVA_EXPERIMENTAL_INTERRUPTION="false")
    result = subprocess.run([sys.executable, "-c", "import offline_ai_companion.config"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Spoken interruption requires" in result.stderr


def test_cancellation_diagnostics_use_fixed_category_not_private_error(capsys):
    from offline_ai_companion.audio.diagnostics import stage
    with pytest.raises(ResponseInterrupted):
        with stage("playback"):
            raise ResponseInterrupted()
    output = capsys.readouterr().out
    assert "status=interrupted" in output and "committed operations" not in output
