"""Validate real audio adapters with synthetic input and fake subprocesses."""

import logging
from itertools import count
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import numpy as np
import pytest
import soundfile as sf

from offline_ai_companion.audio.continuous_recorder import ContinuousRecorder
from offline_ai_companion.core.performance import timed
from offline_ai_companion.llm.ollama import OllamaLLM
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.tts.piper import PiperTTS


def test_vad_segments_synthetic_speech_and_writes_valid_wav(tmp_path, monkeypatch):
    recorder = ContinuousRecorder(silence_duration=0.15, threshold=0.018)
    blocks = [np.zeros((1600, 1), dtype=np.float32)]
    blocks += [np.full((1600, 1), 0.1, dtype=np.float32) for _ in range(3)]
    blocks += [np.zeros((1600, 1), dtype=np.float32) for _ in range(3)]

    class Input:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            for block in blocks:
                self.callback(block, len(block), None, None)
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Input)
    ticks = count()
    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.time.monotonic", lambda: next(ticks) * 0.1)
    path = recorder.record_utterance(tmp_path / "vad.wav")
    audio, rate = sf.read(path)
    assert rate == 16000
    assert len(audio) >= 5 * 1600  # pre-roll, confirmed speech and tail
    assert np.max(audio) > 0.09
    assert sf.info(path).subtype == "PCM_16"


def test_reminder_cancels_vad_capture_without_writing_audio(tmp_path, monkeypatch):
    recorder = ContinuousRecorder()
    interrupt = Event()

    class Input:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def __enter__(self):
            self.callback(np.full((1600, 1), 0.1, dtype=np.float32), 1600, None, None)
            interrupt.set()
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("offline_ai_companion.audio.continuous_recorder.sd.InputStream", Input)
    path = tmp_path / "interrupted.wav"
    assert recorder.record_utterance(path, interrupt_event=interrupt) is None
    assert not path.exists()


def test_adapter_timings_never_include_text_paths_or_model_output(tmp_path, monkeypatch, caplog):
    executable = tmp_path / "private-path.exe"
    model = tmp_path / "private-model.bin"
    audio = tmp_path / "private-audio.wav"
    for path in (executable, model, audio):
        path.touch()
    secret = "Sensitive transcript never in performance logs"

    def run(command, **kwargs):
        if "--output_file" in command:
            Path(command[command.index("--output_file") + 1]).touch()
        return SimpleNamespace(stdout=secret)

    monkeypatch.setattr("subprocess.run", run)
    caplog.set_level(logging.INFO, logger="nova.performance")
    assert WhisperSTT(executable, model).transcribe(audio) == secret
    PiperTTS(executable, model).synthesize(secret, tmp_path / "output.wav")
    client = Mock(spec=httpx.Client)
    client.post.return_value = httpx.Response(200, json={"response": secret}, request=httpx.Request("POST", "http://localhost/api/generate"))
    assert OllamaLLM(client=client).generate(secret) == secret
    messages = [r.getMessage() for r in caplog.records if r.name == "nova.performance"]
    assert len(messages) == 3
    for stage in ("transcription", "tts_generation", "ollama_response"):
        assert any(f"stage={stage} " in message for message in messages)
    assert all("duration_ms=" in message and "status=ok" in message for message in messages)
    assert all(secret not in message and "private" not in message for message in messages)


@pytest.mark.parametrize("exception", [RuntimeError("private error details"), KeyboardInterrupt()])
def test_timing_records_failures_and_interrupts_without_details(caplog, exception):
    caplog.set_level(logging.INFO, logger="nova.performance")

    @timed("test_stage")
    def fails(private_argument):
        raise exception

    with pytest.raises(type(exception)):
        fails("private transcript")
    assert "status=error" in caplog.text
    assert "private" not in caplog.text
