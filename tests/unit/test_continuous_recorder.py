
from threading import Event

import pytest

from offline_ai_companion.audio.continuous_recorder import (
    ContinuousRecorder,
)


def test_default_configuration():
    recorder = ContinuousRecorder()

    assert recorder.sample_rate == 16000
    assert recorder.block_size == 1600
    assert recorder.silence_duration == 1.0


def test_invalid_sample_rate():
    with pytest.raises(ValueError):
        ContinuousRecorder(sample_rate=0)


def test_invalid_silence_duration():
    with pytest.raises(ValueError):
        ContinuousRecorder(silence_duration=0)


def test_invalid_max_duration():
    with pytest.raises(ValueError):
        ContinuousRecorder(max_duration=-1)


def test_recording_can_be_cancelled(tmp_path):
    recorder = ContinuousRecorder()
    stop_event = Event()
    stop_event.set()

    result = recorder.record_utterance(
        tmp_path / "cancelled.wav",
        stop_event,
    )

    assert result is None
