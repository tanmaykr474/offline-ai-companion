
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from offline_ai_companion.tts.piper import PiperTTS


@pytest.fixture
def piper_files(tmp_path):
    executable = tmp_path / "piper.exe"
    model = tmp_path / "voice.onnx"
    output = tmp_path / "speech.wav"

    executable.touch()
    model.touch()

    return executable, model, output


def test_empty_text(piper_files):
    executable, model, output = piper_files
    tts = PiperTTS(executable, model)

    with pytest.raises(ValueError):
        tts.synthesize("   ", output)


def test_missing_executable(piper_files, tmp_path):
    _, model, output = piper_files
    tts = PiperTTS(tmp_path / "missing.exe", model)

    with pytest.raises(FileNotFoundError):
        tts.synthesize("Hello", output)


def test_missing_model(piper_files, tmp_path):
    executable, _, output = piper_files
    tts = PiperTTS(executable, tmp_path / "missing.onnx")

    with pytest.raises(FileNotFoundError):
        tts.synthesize("Hello", output)


@patch("subprocess.run")
def test_successful_synthesis(mock_run, piper_files):
    executable, model, output = piper_files
    tts = PiperTTS(executable, model)

    def create_output(*args, **kwargs):
        output.touch()

    mock_run.side_effect = create_output

    result = tts.synthesize("Hello world", output)

    assert result == output
    assert output.exists()
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_synthesis_timeout(mock_run, piper_files):
    executable, model, output = piper_files
    tts = PiperTTS(executable, model)

    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd="piper",
        timeout=120,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        tts.synthesize("Hello", output)


@patch("subprocess.run")
def test_missing_generated_audio(mock_run, piper_files):
    executable, model, output = piper_files
    tts = PiperTTS(executable, model)

    with pytest.raises(
        RuntimeError,
        match="did not generate",
    ):
        tts.synthesize("Hello", output)
