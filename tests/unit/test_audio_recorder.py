import pytest

from offline_ai_companion.audio.recorder import AudioRecorder


def test_default_recorder_configuration():
    recorder = AudioRecorder()

    assert recorder.sample_rate == 16_000
    assert recorder.channels == 1
    assert recorder.dtype == "float32"


def test_invalid_duration():
    recorder = AudioRecorder()

    with pytest.raises(ValueError):
        recorder.record(
            duration=0,
            output_path="sample-data/audio/test.wav",
        )


def test_negative_duration():
    recorder = AudioRecorder()

    with pytest.raises(ValueError):
        recorder.record(
            duration=-1,
            output_path="sample-data/audio/test.wav",
        )