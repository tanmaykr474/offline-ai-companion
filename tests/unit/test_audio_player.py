
from unittest.mock import patch

import pytest

from offline_ai_companion.audio.player import AudioPlayer


def test_missing_audio_file(tmp_path):
    player = AudioPlayer()

    with pytest.raises(FileNotFoundError):
        player.play(tmp_path / "missing.wav")


@patch("offline_ai_companion.audio.player.sd")
@patch("offline_ai_companion.audio.player.sf")
def test_successful_playback(mock_sf, mock_sd, tmp_path):
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    mock_sf.read.return_value = ([0.0, 0.1], 22050)

    player = AudioPlayer()
    player.play(audio_path)

    mock_sd.play.assert_called_once_with(
        [0.0, 0.1],
        samplerate=22050,
    )
    mock_sd.wait.assert_called_once()
    mock_sd.stop.assert_called_once()
