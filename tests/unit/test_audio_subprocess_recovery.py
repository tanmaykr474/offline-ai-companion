
from pathlib import Path
from unittest.mock import patch

import pytest

from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.tts.piper import PiperTTS


def test_whisper_handles_executable_launch_failure(
    tmp_path: Path,
):
    executable = tmp_path / "whisper.exe"
    model = tmp_path / "model.bin"
    audio = tmp_path / "input.wav"

    for path in (executable, model, audio):
        path.touch()

    stt = WhisperSTT(
        executable=executable,
        model_path=model,
    )

    with patch(
        "offline_ai_companion.stt.whisper.subprocess.run",
        side_effect=OSError("Access denied"),
    ):
        with pytest.raises(
            RuntimeError,
            match="Cannot start Whisper",
        ):
            stt.transcribe(audio)


def test_piper_handles_executable_launch_failure(
    tmp_path: Path,
):
    executable = tmp_path / "piper.exe"
    model = tmp_path / "voice.onnx"
    output = tmp_path / "output.wav"

    executable.touch()
    model.touch()

    tts = PiperTTS(
        executable=executable,
        model_path=model,
    )

    with patch(
        "offline_ai_companion.tts.piper.subprocess.run",
        side_effect=OSError("Access denied"),
    ):
        with pytest.raises(
            RuntimeError,
            match="Cannot start Piper",
        ):
            tts.synthesize("Hello", output)


def test_piper_removes_stale_audio_before_synthesis(
    tmp_path: Path,
):
    executable = tmp_path / "piper.exe"
    model = tmp_path / "voice.onnx"
    output = tmp_path / "output.wav"

    executable.touch()
    model.touch()
    output.write_bytes(b"old audio")

    tts = PiperTTS(
        executable=executable,
        model_path=model,
    )

    with patch(
        "offline_ai_companion.tts.piper.subprocess.run",
        side_effect=OSError("Access denied"),
    ):
        with pytest.raises(RuntimeError):
            tts.synthesize("Hello", output)

    assert not output.exists()
