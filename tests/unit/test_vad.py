
import numpy as np
import pytest

from offline_ai_companion.audio.vad import (
    VoiceActivityDetector,
)


def test_detects_speech_energy():
    vad = VoiceActivityDetector(threshold=0.018)

    audio = np.full(1600, 0.1, dtype=np.float32)

    assert vad.is_speech(audio)


def test_rejects_silence():
    vad = VoiceActivityDetector()

    audio = np.zeros(1600, dtype=np.float32)

    assert not vad.is_speech(audio)


def test_rejects_low_energy_noise():
    vad = VoiceActivityDetector(threshold=0.018)

    audio = np.full(1600, 0.005, dtype=np.float32)

    assert not vad.is_speech(audio)


def test_handles_empty_audio():
    vad = VoiceActivityDetector()

    assert not vad.is_speech(
        np.array([], dtype=np.float32)
    )


def test_rejects_invalid_threshold():
    with pytest.raises(ValueError):
        VoiceActivityDetector(threshold=0)


def test_rms_returns_zero_for_empty_audio():
    assert VoiceActivityDetector.rms(
        np.array([], dtype=np.float32)
    ) == 0.0


def test_rms_calculates_signal_energy():
    audio = np.full(1600, 0.1, dtype=np.float32)

    assert VoiceActivityDetector.rms(audio) == pytest.approx(
        0.1,
        abs=1e-6,
    )


def test_rejects_nonfinite_threshold():
    with pytest.raises(ValueError):
        VoiceActivityDetector(threshold=float("nan"))

    with pytest.raises(ValueError):
        VoiceActivityDetector(threshold=float("inf"))
