
from pathlib import Path
from unittest.mock import patch
import subprocess

import pytest

from offline_ai_companion.stt.whisper import WhisperSTT


@pytest.fixture
def stt_files(tmp_path):
    executable = tmp_path / "whisper-cli.exe"
    model = tmp_path / "model.bin"
    audio = tmp_path / "audio.wav"

    executable.touch()
    model.touch()
    audio.touch()

    return executable, model, audio


def test_missing_audio_file(stt_files, tmp_path):
    executable, model, _ = stt_files

    stt = WhisperSTT(executable, model)

    with pytest.raises(FileNotFoundError):
        stt.transcribe(tmp_path / "missing.wav")


def test_missing_executable(stt_files, tmp_path):
    _, model, audio = stt_files

    stt = WhisperSTT(
        tmp_path / "missing.exe",
        model,
    )

    with pytest.raises(FileNotFoundError):
        stt.transcribe(audio)


def test_missing_model(stt_files, tmp_path):
    executable, _, audio = stt_files

    stt = WhisperSTT(
        executable,
        tmp_path / "missing.bin",
    )

    with pytest.raises(FileNotFoundError):
        stt.transcribe(audio)


@patch("subprocess.run")
def test_successful_transcription(mock_run, stt_files):
    executable, model, audio = stt_files

    mock_run.return_value.stdout = (
        "Hello, this is my AI companion.\n"
    )

    stt = WhisperSTT(executable, model)

    result = stt.transcribe(audio)

    assert result == "Hello, this is my AI companion."
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_transcription_timeout(mock_run, stt_files):
    executable, model, audio = stt_files

    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd="whisper-cli",
        timeout=120,
    )

    stt = WhisperSTT(executable, model)

    with pytest.raises(RuntimeError, match="timed out"):
        stt.transcribe(audio)
